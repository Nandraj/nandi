import io
import json
import shutil
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, llm, models as dtmodels, pipeline
from .dt_client import ADV_FIELDS, SAMPLERS
from .pb import imageService_pb2 as pb

app = FastAPI(title="Nandi", description="Unofficial companion app for Draw Things")
app.add_middleware(CORSMiddleware, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?", allow_methods=["*"], allow_headers=["*"])
gpu_queue = ThreadPoolExecutor(max_workers=1)   # one video job at a time

ASPECTS = {"landscape": (832, 448), "portrait": (448, 832), "square": (640, 640), "wide": (1024, 576)}


@app.on_event("startup")
def startup():
    db.init()
    db.run("UPDATE projects SET status='failed', message='Interrupted by server restart — resume to continue' "
           "WHERE status IN ('generating','scripting')")
    db.run("UPDATE chunks SET status='pending' WHERE status='running'")


def get_project(pid: int) -> dict:
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404, "project not found")
    return p


def check_size(w: int, h: int) -> tuple:
    if w % 64 or h % 64:
        raise HTTPException(400, "width and height must be multiples of 64")
    if not (256 <= w <= 2048 and 256 <= h <= 2048):
        raise HTTPException(400, "width and height must be between 256 and 2048")
    return w, h


MODES = ("script", "image", "video", "t2v", "character")
NUMERIC = {"steps": (int, 1, 200), "cfg": (float, 0, 50), "shift": (float, 0, 20), "strength": (float, 0, 1),
           "clip_skip": (int, 1, 12), "refiner_start": (float, 0, 1), "frames": (int, 5, 401), "fps": (int, 1, 60),
           "count": (int, 1, 16)}
IMAGE_KEYS = ("model", "steps", "cfg", "shift", "sampler", "strength", "clip_skip", "count")
VIDEO_KEYS = ("model", "refiner", "refiner_start", "steps", "cfg", "shift", "sampler", "strength", "clip_skip", "frames", "fps")


def clean_loras(raw, pad: int = 0, limit: int = 4) -> list:
    loras = []
    for l in (raw or [])[:limit]:
        mode = l.get("mode", "all")
        if mode not in ("all", "base", "refiner"):
            raise ValueError("LoRA mode must be all, base or refiner")
        loras.append({"file": str(l.get("file", "")).strip(), "weight": float(l.get("weight", 1.0)), "mode": mode})
    while len(loras) < pad:
        loras.append(dict(db.EMPTY_LORA))
    return loras


def clean_adv(raw) -> dict:
    out = {}
    for k, v in (raw or {}).items():
        if k not in ADV_FIELDS or v is None or v == "":
            continue
        kind = ADV_FIELDS[k][1]
        try:
            out[k] = (bool(v) if kind == "b" else str(v) if kind == "s" else float(v) if kind == "f" else int(v))
        except (TypeError, ValueError):
            raise ValueError(f"advanced option {k} has an invalid value")
    return out


def clean_model_params(o, keys) -> dict:
    out = {}
    for k in keys:
        v = (o or {}).get(k)
        if v is None or (v == "" and k != "refiner"):
            continue
        if k in NUMERIC:
            typ, lo, hi = NUMERIC[k]
            try:
                v = typ(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be a number")
            if not lo <= v <= hi:
                raise ValueError(f"{k} must be between {lo} and {hi}")
        elif k == "sampler":
            if v not in SAMPLERS:
                raise ValueError(f"unknown sampler {v}")
        else:
            v = str(v).strip()
        out[k] = v
    out["adv"] = clean_adv((o or {}).get("adv"))
    return out


def clean_options(o: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in db.DEFAULT_OPTIONS.items()}
    if o.get("seed_mode", "random") not in ("random", "fixed", "increment"):
        raise ValueError("seed_mode must be random, fixed or increment")
    out["seed_mode"] = o.get("seed_mode", "random")
    out["seed"] = int(o.get("seed") or 0)
    if not 0 <= out["seed"] < 2**32:
        raise ValueError("seed must be between 0 and 4294967295")
    out["loras"] = clean_loras(o.get("loras"), pad=2)[:2]
    out["extra_loras"] = [l for l in clean_loras(o.get("extra_loras"), limit=12) if l["file"]]
    ch = o.get("character") or {}
    try:
        count = int(ch.get("count") or 20)
    except (TypeError, ValueError):
        raise ValueError("number of character images must be a number")
    if not 1 <= count <= 200:
        raise ValueError("number of character images must be between 1 and 200")
    out["character"] = {"count": count, "trigger": str(ch.get("trigger") or "").strip()[:60]}
    pr = o.get("prompts") or {}
    out["prompts"] = {
        "image": str(pr.get("image") or "").strip(), "image_negative": str(pr.get("image_negative") or "").strip(),
        "video": str(pr.get("video") or "").strip(),
        "video_negative": None if pr.get("video_negative") is None else str(pr["video_negative"]).strip(),
    }
    out["image"] = clean_model_params(o.get("image"), IMAGE_KEYS)
    out["image"]["loras"] = [l for l in clean_loras((o.get("image") or {}).get("loras")) if l["file"]]
    out["video"] = clean_model_params(o.get("video"), VIDEO_KEYS)
    out["style"] = o.get("style") or ""
    if out["style"] not in ("", "realistic", "cartoon"):
        raise ValueError("style must be empty, realistic or cartoon")
    return out


class OptionsReq(BaseModel):
    width: int
    height: int
    options: dict


@app.put("/api/projects/{pid}/options")
def put_options(pid: int, body: OptionsReq):
    p = get_project(pid)
    if p["status"] in ("generating", "scripting"):
        raise HTTPException(409, "project is busy")
    w, h = check_size(body.width, body.height)
    try:
        opts = clean_options(body.options)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.update("projects", pid, width=w, height=h, options=json.dumps(opts))
    return full(get_project(pid))


def _lora_names_from_override(blob: bytes) -> dict:
    """MetadataOverride.loras is a JSON array of LoRA specs ({name, file, ...}) when the server provides it."""
    out = {}
    try:
        for item in json.loads(blob.decode()):
            if isinstance(item, dict) and item.get("file"):
                out[item["file"]] = item.get("name") or item["file"]
    except Exception:  # noqa: BLE001
        pass
    return out


@app.get("/api/loras")
def list_loras():
    """Downloaded LoRAs: server metadata (Echo) first, then any *lora* files the server lists,
    then the local Draw Things models folder if readable."""
    s = db.get_settings()
    found: dict = {}
    source = "none"
    reachable, browsing = False, False
    try:
        c = pipeline.client_from(s)
        req = pb.EchoRequest(name="nandi")
        if s["dt_secret"]:
            req.sharedSecret = s["dt_secret"]
        echo = c.stub.Echo(req, timeout=15)
        c.close()
        reachable = True
        browsing = bool(echo.files) or (echo.HasField("override") and len(echo.override.loras) > 2)
        if echo.HasField("override"):
            found.update(_lora_names_from_override(echo.override.loras))
        for f in echo.files:
            if "lora" in f.lower():
                found.setdefault(f, f)
        if found:
            source = "drawthings"
    except Exception:  # noqa: BLE001
        pass
    try:
        d = Path(s["dt_models_dir"]).expanduser()
        for f in d.iterdir():
            if "lora" in f.name.lower() and f.suffix == ".ckpt":
                found.setdefault(f.name, f.name)
        if found and source == "none":
            source = "folder"
    except Exception:  # noqa: BLE001
        pass
    items = [{"file": f, "name": n} for f, n in sorted(found.items(), key=lambda x: x[1].lower())]
    return {"source": source, "reachable": reachable, "browsing": browsing, "loras": items,
            "defaults": _lightning_defaults(items)}


def _lightning_defaults(items: list) -> dict:
    """Pick the Wan 2.2 A14B Lightning high-noise (base) and low-noise (refiner) LoRAs, preferring I2V ones."""
    import re

    def best(side: str):
        pat = r"high|hne" if side == "high" else r"low|lne"
        cands = []
        for it in items:
            t = f"{it['file']} {it['name']}".lower()
            if "lightning" in t and re.search(pat, t):
                cands.append((("i2v" in t) * 2 + ("a14b" in t), it["file"]))
        return max(cands)[1] if cands else None

    return {"lora1": best("high"), "lora2": best("low")}


@app.get("/api/models")
def list_models():
    """Everything Draw Things can offer: installed models (image/video, with suggested settings), upscalers, samplers."""
    s = db.get_settings()
    raw, upscalers = [], []
    reachable = browsing = False
    try:
        c = pipeline.client_from(s)
        req = pb.EchoRequest(name="nandi")
        if s["dt_secret"]:
            req.sharedSecret = s["dt_secret"]
        echo = c.stub.Echo(req, timeout=15)
        c.close()
        reachable = True
        files = list(echo.files)
        blob = echo.override.models if echo.HasField("override") else b""
        raw = dtmodels.parse_models(blob, files)
        if echo.HasField("override"):
            upscalers = dtmodels.parse_simple_list(echo.override.upscalers)
        browsing = bool(raw)
        for f in files:
            if "esrgan" in f.lower() or "upscal" in f.lower():
                if not any(u["file"] == f for u in upscalers):
                    upscalers.append({"file": f, "name": f})
    except Exception:  # noqa: BLE001
        pass
    try:   # local models folder (same machine)
        known = {m["file"] for m in raw}
        for f in sorted(Path(s["dt_models_dir"]).expanduser().iterdir()):
            if f.suffix == ".ckpt" and f.name not in known and not dtmodels.SKIP_RE.search(f.name):
                raw.append({"file": f.name, "name": f.name, "version": ""})
    except Exception:  # noqa: BLE001
        pass
    return {"reachable": reachable, "browsing": browsing, "models": dtmodels.classify(raw), "upscalers": upscalers,
            "samplers": list(SAMPLERS),
            "defaults": {"image": s["keyframe_model"], "video": s["hne_model"]}}


class EnhanceReq(BaseModel):
    prompt: str
    kind: str = "image"


@app.post("/api/enhance")
def enhance(body: EnhanceReq):
    if not body.prompt.strip():
        raise HTTPException(400, "write a prompt first")
    try:
        return {"prompt": llm.enhance_prompt(db.get_settings(), body.prompt.strip(), body.kind if body.kind in ("video", "character") else "image")}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Prompt enhancement failed: {e}"[:400])


class FilesReq(BaseModel):
    files: list


@app.post("/api/files-exist")
def files_exist(body: FilesReq):
    c = pipeline.client_from(db.get_settings())
    try:
        r = c.stub.FilesExist(pb.FileListRequest(files=[f for f in body.files if f]), timeout=15)
        return dict(zip(r.files, r.existences))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Draw Things unreachable: {e}")
    finally:
        c.close()


def full(p: dict) -> dict:
    p = dict(p)
    p["options"] = db.project_options(p)
    idir = db.DATA_DIR / "projects" / str(p["id"]) / "images"
    p["images"] = [f"projects/{p['id']}/images/{f.name}" for f in sorted(idir.glob("*.png"))] if idir.exists() else []
    p["sample"] = f"projects/{p['id']}/sample.png" if (db.DATA_DIR / "projects" / str(p["id"]) / "sample.png").exists() else None
    p["script"] = json.loads(p["script"]) if p["script"] else None
    p["refs"] = db.q("SELECT id, idx, filename FROM refs WHERE project_id=? ORDER BY idx", (p["id"],))
    p["chunks"] = db.q("SELECT id, idx, prompt, scene_idx, gen_frames, keep_frames, status, progress, error, video_path, seed "
                       "FROM chunks WHERE project_id=? ORDER BY idx", (p["id"],))
    return p


# ---------------------------------------------------------------- settings / health
@app.get("/api/settings")
def get_settings():
    return db.public_settings()


@app.put("/api/settings")
def put_settings(body: dict):
    db.save_settings(body)
    return db.public_settings()


@app.post("/api/llm/test")
def llm_test(body: dict):
    """Test an LLM connection with the (possibly unsaved) form values; unchanged secrets fall back to the saved ones."""
    s = db.get_settings()
    for k in ("llm_provider", "llm_base_url", "llm_model", "llm_api_key"):
        if k in body and not (k == "llm_api_key" and body[k] == db.MASK):
            s[k] = body[k]
    try:
        names = llm.list_models(s)
        return {"ok": True, "models": names, "model_present": s["llm_model"] in names if names else None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300], "models": []}


@app.get("/api/health")
def health():
    s = db.get_settings()
    out = {"ollama": {"ok": False}, "drawthings": {"ok": False}}
    try:
        names = llm.list_models(s)
        out["ollama"] = {"ok": True, "provider": s["llm_provider"], "models": names, "model_present": (s["llm_model"] in names) if names else True}
    except Exception as e:  # noqa: BLE001
        out["ollama"].update(error=str(e), provider=s["llm_provider"])
    try:
        c = pipeline.client_from(s)
        echo = c.echo()
        names = [s["hne_model"], s["lne_model"], s["keyframe_model"], "umt5_xxl_encoder_q8p.ckpt", "wan_v2.1_video_vae_f16.ckpt"]
        ex = c.stub.FilesExist(pb.FileListRequest(files=names), timeout=15)
        out["drawthings"] = {"ok": not echo["shared_secret_missing"], "shared_secret_missing": echo["shared_secret_missing"],
                             "files": dict(zip(ex.files, ex.existences))}
        c.close()
    except Exception as e:  # noqa: BLE001
        out["drawthings"]["error"] = str(e)
    return out


# ---------------------------------------------------------------- projects
@app.get("/api/projects")
def list_projects():
    return db.q("SELECT id,title,kind,mode,duration,status,message,video_path,created FROM projects ORDER BY id DESC")


@app.post("/api/projects")
async def create_project(
    title: str = Form(""), kind: str = Form("movie"), mode: str = Form("script"), prompt: str = Form(""), duration: int = Form(4),
    aspect: str = Form("landscape"), width: int = Form(0), height: int = Form(0), options: str = Form("{}"),
    images: List[UploadFile] = File(default=[]),
):
    if mode not in MODES:
        raise HTTPException(400, f"mode must be one of {list(MODES)}")
    if mode != "script":
        kind = "clip"
    elif kind not in ("movie", "clip"):
        raise HTTPException(400, "kind must be movie or clip")
    if not 4 <= duration <= 1800:
        raise HTTPException(400, "duration must be 4–1800 seconds")
    if aspect == "custom":
        w, h = check_size(width, height)
    elif aspect in ASPECTS:
        w, h = ASPECTS[aspect]
    else:
        raise HTTPException(400, f"aspect must be custom or one of {list(ASPECTS)}")
    try:
        opts = clean_options(json.loads(options or "{}"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    pr = opts["prompts"]
    if mode == "image" and not pr["image"]:
        raise HTTPException(400, "write an image prompt")
    if mode == "character" and not pr["image"] and not any(f.filename for f in images):
        raise HTTPException(400, "describe the character or add a reference image")
    if mode == "video" and not pr["video"]:
        raise HTTPException(400, "write a video prompt")
    if mode == "t2v" and not (pr["image"] and pr["video"]):
        raise HTTPException(400, "text-to-video needs both an image prompt and a video prompt")
    main = (prompt.strip() or pr["video"] or pr["image"]) if mode != "script" else prompt.strip()
    if mode == "character":
        main = pr["image"] or "Character from reference image"
    if not main:
        raise HTTPException(400, "prompt is required")
    import time
    pid = db.run("INSERT INTO projects(title,kind,mode,prompt,duration,width,height,options,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (title.strip() or main[:40], kind, mode, main, duration, w, h, json.dumps(opts), time.time(), time.time()))
    await save_images(pid, images)
    return full(get_project(pid))


async def save_images(pid: int, images: List[UploadFile]):
    d = pipeline.project_dir(pid) / "refs"
    d.mkdir(exist_ok=True)
    idx = (db.one("SELECT COALESCE(MAX(idx),-1)+1 AS n FROM refs WHERE project_id=?", (pid,)) or {"n": 0})["n"]
    for f in images:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            raise HTTPException(400, f"unsupported image type {ext}")
        name = f"{uuid.uuid4().hex[:10]}{ext}"
        with open(d / name, "wb") as out:
            shutil.copyfileobj(f.file, out)
        db.run("INSERT INTO refs(project_id,idx,filename) VALUES(?,?,?)", (pid, idx, name))
        idx += 1


@app.get("/api/projects/{pid}")
def project(pid: int):
    return full(get_project(pid))


@app.delete("/api/projects/{pid}")
def delete_project(pid: int):
    get_project(pid)
    pipeline.cancel_events.setdefault(pid, threading.Event()).set()
    db.run("DELETE FROM projects WHERE id=?", (pid,))
    shutil.rmtree(db.DATA_DIR / "projects" / str(pid), ignore_errors=True)
    return {"ok": True}


@app.post("/api/projects/{pid}/refs")
async def add_refs(pid: int, images: List[UploadFile] = File(...)):
    get_project(pid)
    await save_images(pid, images)
    return full(get_project(pid))


@app.delete("/api/projects/{pid}/refs/{rid}")
def del_ref(pid: int, rid: int):
    r = db.one("SELECT * FROM refs WHERE id=? AND project_id=?", (rid, pid))
    if r:
        (db.DATA_DIR / "projects" / str(pid) / "refs" / r["filename"]).unlink(missing_ok=True)
        db.run("DELETE FROM refs WHERE id=?", (rid,))
    return full(get_project(pid))


# ---------------------------------------------------------------- script
class ScriptReq(BaseModel):
    feedback: Optional[str] = ""


def _script_job(pid: int, feedback: str):
    try:
        p = get_project(pid)
        s = db.get_settings()
        prev = json.loads(p["script"]) if p["script"] else None
        refs = [db.DATA_DIR / "projects" / str(pid) / "refs" / r["filename"]
                for r in db.q("SELECT filename FROM refs WHERE project_id=? ORDER BY idx", (pid,))]
        p = {**p, "style": db.project_options(p).get("style", "")}
        script = llm.generate_script(s, p, refs, feedback, prev if feedback else None)
        db.update("projects", pid, script=json.dumps(script, ensure_ascii=False), status="script_ready",
                  message="Script ready for review")
        pipeline.refresh_chunks(pid)
    except Exception as e:  # noqa: BLE001
        db.update("projects", pid, status="draft", message=f"Script generation failed: {e}"[:500])


@app.post("/api/projects/{pid}/script/generate")
def gen_script(pid: int, body: ScriptReq = ScriptReq()):
    p = get_project(pid)
    if p["mode"] != "script":
        raise HTTPException(400, "this project type has no script; its prompts are used directly")
    if p["status"] in ("generating", "scripting"):
        raise HTTPException(409, "project is busy")
    db.update("projects", pid, status="scripting", message="Writing script with " + db.get_settings()["llm_model"])
    threading.Thread(target=_script_job, args=(pid, body.feedback or ""), daemon=True).start()
    return full(get_project(pid))


@app.put("/api/projects/{pid}/script")
def put_script(pid: int, script: dict):
    p = get_project(pid)
    if p["status"] in ("generating", "scripting"):
        raise HTTPException(409, "project is busy")
    if not script.get("scenes"):
        raise HTTPException(400, "script needs at least one scene")
    for sc in script["scenes"]:
        sc["duration_sec"] = float(sc.get("duration_sec") or 8)
    db.update("projects", pid, script=json.dumps(script, ensure_ascii=False), status="script_ready")
    pipeline.refresh_chunks(pid)
    return full(get_project(pid))


# ---------------------------------------------------------------- generation
def _start(pid: int, rebuild: bool):
    p = get_project(pid)
    if p["status"] in ("generating", "scripting"):
        raise HTTPException(409, "project is busy")
    if p["mode"] in ("image", "character"):
        db.update("projects", pid, status="generating", message="Queued")
        if p["mode"] == "character":   # no reference image -> sample first; the user confirms it before the full set
            has_refs = bool(db.q("SELECT 1 FROM refs WHERE project_id=?", (pid,)))
            gpu_queue.submit(pipeline.run_character if has_refs else pipeline.run_character_sample, pid)
        else:
            gpu_queue.submit(pipeline.run_image, pid)
        return full(get_project(pid))
    if rebuild:
        if p["mode"] == "script" and not p["script"]:
            raise HTTPException(400, "no script yet")
        if p["mode"] == "t2v":   # new prompts must give a new first image
            (pipeline.project_dir(pid) / "keyframe.png").unlink(missing_ok=True)
        pipeline.build_chunks(pid)
        db.update("projects", pid, status="generating", message="Queued", video_path=None)
    else:
        if not db.q("SELECT 1 FROM chunks WHERE project_id=?", (pid,)):
            raise HTTPException(400, "nothing to resume; start the generation first")
        db.update("projects", pid, status="generating", message="Queued")
    gpu_queue.submit(pipeline.run_generation, pid)
    return full(get_project(pid))


@app.post("/api/projects/{pid}/approve")
def approve(pid: int):
    return _start(pid, True)


@app.post("/api/projects/{pid}/resume")
def resume(pid: int):
    return _start(pid, False)


def _idle_project(pid: int) -> dict:
    p = get_project(pid)
    if p["status"] in ("generating", "scripting"):
        raise HTTPException(409, "project is busy; cancel first")
    return p


@app.post("/api/projects/{pid}/chunks/{idx}/reset")
def reset_chunks(pid: int, idx: int):
    """Redo chunk `idx` and all later chunks (click Resume afterwards)."""
    _idle_project(pid)
    if not db.one("SELECT 1 AS x FROM chunks WHERE project_id=? AND idx=?", (pid, idx)):
        raise HTTPException(404, "chunk not found")
    pipeline.reset_from(pid, idx)
    pipeline.refresh_chunks(pid)
    db.update("projects", pid, status="cancelled", video_path=None,
              message=f"Chunks from {idx + 1} onward were reset — resume to regenerate them")
    return full(get_project(pid))


@app.put("/api/projects/{pid}/chunks/{idx}/prompt")
def set_chunk_prompt(pid: int, idx: int, body: dict):
    _idle_project(pid)
    prompt = (body.get("prompt") or "").strip()
    ch = db.one("SELECT id, status FROM chunks WHERE project_id=? AND idx=?", (pid, idx))
    if not ch or not prompt:
        raise HTTPException(400, "chunk not found or empty prompt")
    if ch["status"] == "done":
        raise HTTPException(409, "chunk already rendered; use redo from here first")
    db.update("chunks", ch["id"], prompt=prompt)
    return full(get_project(pid))


@app.post("/api/projects/{pid}/character/confirm")
def character_confirm(pid: int):
    """Use the current sample image as the reference for all character images."""
    p = get_project(pid)
    if p["mode"] != "character":
        raise HTTPException(400, "not a character project")
    if p["status"] in ("generating", "scripting"):
        raise HTTPException(409, "project is busy")
    if not (pipeline.project_dir(pid) / "sample.png").exists() and not db.q("SELECT 1 FROM refs WHERE project_id=?", (pid,)):
        raise HTTPException(400, "generate a sample image first")
    db.update("projects", pid, status="generating", message="Queued")
    gpu_queue.submit(pipeline.run_character, pid)
    return full(get_project(pid))


@app.get("/api/projects/{pid}/dataset.zip")
def character_dataset(pid: int):
    """Generated character images + one caption .txt per image, ready for LoRA training."""
    get_project(pid)
    pdir = pipeline.project_dir(pid)
    files = sorted((pdir / "images").glob("*.png"))
    if not files:
        raise HTTPException(404, "no images yet")
    cap_file = pdir / "captions.json"
    caps = json.loads(cap_file.read_text()) if cap_file.exists() else {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for f in files:
            z.write(f, f.name)
            z.writestr(f.stem + ".txt", caps.get(f.name, ""))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="character_{pid}_dataset.zip"'})


@app.post("/api/projects/{pid}/cancel")
def cancel(pid: int):
    get_project(pid)
    pipeline.cancel_events.setdefault(pid, threading.Event()).set()
    return {"ok": True}


(db.DATA_DIR / "projects").mkdir(exist_ok=True)
app.mount("/media/projects", StaticFiles(directory=db.DATA_DIR / "projects"), name="media")  # never expose the sqlite file

_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
