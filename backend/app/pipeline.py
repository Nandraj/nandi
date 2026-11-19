"""Chunked video generation (default Wan 2.2 I2V: 81 frames @16fps per chunk, last frame -> next chunk) and image generation."""
from __future__ import annotations
import json
import math
import re
import shutil
import threading
import time
from pathlib import Path

from PIL import Image, ImageOps

from . import character, db, video
from .dt_client import DrawThingsClient, GenerationCancelled, SAMPLERS, build_config, encode_image

CHUNK_FRAMES = 81           # Wan 2.2 native training length; longer clips tend to loop back to the start pose
FPS = video.FPS

cancel_events: dict[int, threading.Event] = {}


def project_dir(pid: int) -> Path:
    d = db.DATA_DIR / "projects" / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def valid_frames(n: int) -> int:
    """Video models need 4k+1 frames."""
    return max(5, 4 * math.ceil((n - 1) / 4) + 1)


def video_timing(opts: dict) -> tuple[int, int]:
    """-> (frames per chunk, fps) for the project's video model."""
    v = opts["video"]
    return valid_frames(int(v.get("frames") or CHUNK_FRAMES)), max(1, int(v.get("fps") or FPS))


def plan_chunks(duration: int, chunk: int = CHUNK_FRAMES, fps: int = FPS) -> list[tuple[int, int, int]]:
    """-> [(gen_frames, keep_frames, start_frame_in_final)] ."""
    new_per_chunk = chunk - 1   # later chunks repeat the seed frame
    total = max(fps, duration * fps)
    out, done = [], 0
    while done < total:
        remaining = total - done
        if not out:
            keep = min(chunk, remaining)
            gen = chunk if remaining >= chunk else valid_frames(keep)
        else:
            keep = min(new_per_chunk, remaining)
            gen = chunk if remaining >= new_per_chunk else valid_frames(keep + 1)
        out.append((gen, keep, done))
        done += keep
    return out


def scene_at(script: dict, t: float) -> int:
    acc = 0.0
    scenes = script["scenes"]
    for i, s in enumerate(scenes):
        acc += s["duration_sec"]
        if t < acc:
            return i
    return len(scenes) - 1


def build_prompt(script: dict, sc: dict) -> str:
    """Action first (what Wan must animate), then short style. Character detail is already in the scene prompt;
    only characters named in the scene but missing a description there are prepended."""
    action = sc["visual_prompt"].strip()
    style = (script.get("style") or "").strip()
    style = style.split(". No dialogue")[0].rstrip(".")
    low = action.lower()
    extra = " ".join(f"{c['name']}: {c['description'].rstrip('.')}." for c in script.get("characters", [])
                     if c["name"].lower() in low and len(action.split()) < 45)
    parts = [extra, action, f"Style: {style}." if style else ""]
    return " ".join(x for x in parts if x)


def build_chunks(pid: int):
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    opts = db.project_options(p)
    chunk, fps = video_timing(opts)
    script = json.loads(p["script"]) if p["script"] else None
    db.run("DELETE FROM chunks WHERE project_id=?", (pid,))
    for i, (gen, keep, start) in enumerate(plan_chunks(p["duration"], chunk, fps)):
        if script:
            si = scene_at(script, (start + keep / 2) / fps)
            prompt = build_prompt(script, script["scenes"][si])
        else:   # direct modes: the same typed prompt for every chunk
            si, prompt = 0, opts["prompts"]["video"] or p["prompt"]
        db.run("INSERT INTO chunks(project_id,idx,prompt,scene_idx,gen_frames,keep_frames) VALUES(?,?,?,?,?,?)",
               (pid, i, prompt, si, gen, keep))


def refresh_chunks(pid: int):
    """After the script changed: update prompt/scene of chunks that are not finished yet."""
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    chunks = db.q("SELECT * FROM chunks WHERE project_id=? ORDER BY idx", (pid,))
    if not chunks or not p["script"]:
        return
    chunk, fps = video_timing(db.project_options(p))
    script = json.loads(p["script"])
    for ch, (gen, keep, start) in zip(chunks, plan_chunks(p["duration"], chunk, fps)):
        if ch["status"] == "done":
            continue
        si = scene_at(script, (start + keep / 2) / fps)
        db.update("chunks", ch["id"], prompt=build_prompt(script, script["scenes"][si]), scene_idx=si)


def reset_from(pid: int, idx: int):
    """Throw away chunk `idx` and everything after it (each chunk starts from the previous one's last frame)."""
    pdir = project_dir(pid)
    for ch in db.q("SELECT id, idx FROM chunks WHERE project_id=? AND idx>=?", (pid, idx)):
        shutil.rmtree(pdir / f"chunk_{ch['idx']:03d}", ignore_errors=True)
        db.update("chunks", ch["id"], status="pending", progress=0, error="", video_path=None, last_frame=None, start_image=None)
    if idx == 0:
        (pdir / "keyframe.png").unlink(missing_ok=True)
    (pdir / "final.mp4").unlink(missing_ok=True)


def fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (w, h), Image.Resampling.LANCZOS)


LORA_MODES = {"all": 0, "base": 1, "refiner": 2}


def lora_tuples(loras: list):
    return [(l["file"].strip(), max(0.0, float(l.get("weight", 1.0))), LORA_MODES.get(l.get("mode", "all"), 0))
            for l in (loras or []) if l.get("file", "").strip()]


def seed_for(opts: dict, idx: int) -> int:
    import random
    if opts["seed_mode"] == "fixed":
        return int(opts["seed"]) % 2**32
    if opts["seed_mode"] == "increment":
        return (int(opts["seed"]) + idx) % 2**32
    return random.randint(1, 2**32 - 1)


def client_from(s: dict) -> DrawThingsClient:
    return DrawThingsClient(s["dt_host"], int(s["dt_port"]), bool(s["dt_tls"]), s["dt_secret"])


STYLES = {
    "realistic": ("photorealistic, realistic, live-action look, natural lighting, real textures, shot on camera",
                  "cartoon, animated, anime, illustration, drawing, painting, 3d render, cgi, toy-like, flat colors"),
    "cartoon": ("cartoon style, animated, stylized 2D animation, bold outlines, vibrant colors, hand-drawn look",
                "photorealistic, realistic, photograph, live action, real people, film grain"),
}


def apply_style(prompt: str, negative: str, style: str) -> tuple[str, str]:
    """Inject look-defining words so the model clearly renders a realistic or a cartoon result."""
    if style not in STYLES:
        return prompt, negative
    pos, neg = STYLES[style]
    join = lambda a, b: f"{a.rstrip(' ,.')}, {b}" if a.strip() else b  # noqa: E731
    return join(prompt, pos), join(negative, neg)


def _pick(v, default):
    return default if v is None or v == "" else v


def image_params(s: dict, opts: dict, has_ref: bool = False) -> dict:
    """Text-to-image (or image-to-image) parameters: project override first, then Settings' first-frame defaults."""
    i = opts["image"]
    return dict(
        model=i.get("model") or s["keyframe_model"],
        steps=int(_pick(i.get("steps"), s["keyframe_steps"])), cfg=float(_pick(i.get("cfg"), s["keyframe_cfg"])),
        shift=float(_pick(i.get("shift"), s["keyframe_shift"])), sampler=SAMPLERS[i.get("sampler") or s["keyframe_sampler"]],
        clip_skip=int(_pick(i.get("clip_skip"), 1)), strength=float(_pick(i.get("strength"), 0.7 if has_ref else 1.0)),
        loras=lora_tuples(i.get("loras")), adv=i.get("adv") or {}, count=max(1, min(16, int(_pick(i.get("count"), 1)))),
    )


def video_params(s: dict, opts: dict) -> dict:
    """Video model parameters: project override first, then Settings (Wan 2.2 A14B high/low-noise pair)."""
    v = opts["video"]
    custom = bool(v.get("model"))
    loras = lora_tuples(opts["loras"]) + lora_tuples(opts.get("extra_loras"))   # 2 fixed slots + any number of extras
    steps, cfg = _pick(v.get("steps"), None), _pick(v.get("cfg"), None)
    if steps is None or cfg is None:
        lightning = any("lightning" in l[0].lower() for l in loras)   # distilled LoRAs: few steps, no CFG
        steps = int(steps if steps is not None else (s["lightning_steps"] if lightning else s["steps"]))
        cfg = float(cfg if cfg is not None else (s["lightning_cfg"] if lightning else s["cfg"]))
    return dict(
        model=v.get("model") or s["hne_model"],
        refiner=v["refiner"] if "refiner" in v else ("" if custom else s["lne_model"]),
        refiner_start=float(_pick(v.get("refiner_start"), s["refiner_start"])),
        steps=int(steps), cfg=float(cfg), shift=float(_pick(v.get("shift"), s["shift"])),
        sampler=SAMPLERS[v.get("sampler") or s["sampler"]], clip_skip=int(_pick(v.get("clip_skip"), 1)),
        strength=float(_pick(v.get("strength"), 1.0)), loras=loras, adv=v.get("adv") or {},
    )


def video_negative(s: dict, opts: dict) -> str:
    n = opts["prompts"].get("video_negative")
    return s["negative_prompt"] if n is None else n


def make_keyframe(client, s, p, opts, prompt: str, out: Path, ev, seed=None):
    """Render a start frame with a text-to-image model (first chunk without refs, or a scene that changes location)."""
    ip = image_params(s, opts)
    cfg = build_config(width=p["width"], height=p["height"], model=ip["model"], steps=ip["steps"], cfg=ip["cfg"], shift=ip["shift"],
                       frames=1, sampler=ip["sampler"], seed_mode=2, seed=seed, clip_skip=ip["clip_skip"],
                       loras=ip["loras"], adv=ip["adv"])
    prompt, negative = apply_style(prompt, opts["prompts"].get("image_negative") or "", opts.get("style", ""))
    frames = client.generate(prompt=prompt, negative=negative, config=cfg, cancel_event=ev,
                             on_progress=lambda st, n: db.update("projects", p["id"], message=f"Rendering first image ({st} {n})"))
    frames[0].save(out)


def _retry_generate(client, pid, label, **kw):
    for attempt in range(3):   # Draw Things sometimes drops the socket on long runs; retry before failing
        try:
            return client.generate(**kw)
        except RuntimeError as e:
            if attempt == 2 or "UNAVAILABLE" not in str(e):
                raise
            db.update("projects", pid, message=f"{label}: connection lost, retrying ({attempt + 1}/2)…")
            time.sleep(10)


def run_image(pid: int):
    """Image-only mode: render `count` images with the project's image model (optionally from a reference image)."""
    ev = cancel_events.setdefault(pid, threading.Event())
    ev.clear()
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    s = db.get_settings()
    opts = db.project_options(p)
    pdir = project_dir(pid)
    client = client_from(s)
    try:
        refs = db.q("SELECT * FROM refs WHERE project_id=? ORDER BY idx", (pid,))
        ip = image_params(s, opts, bool(refs))
        idir = pdir / "images"
        shutil.rmtree(idir, ignore_errors=True)
        idir.mkdir()
        init = None
        if refs:
            init = encode_image(fit_cover(Image.open(pdir / "refs" / refs[0]["filename"]), p["width"], p["height"]), p["width"], p["height"])
        db.update("projects", pid, status="generating", message="Starting…", video_path=None)
        for i in range(ip["count"]):
            if ev.is_set():
                raise GenerationCancelled()
            seed = seed_for(opts, i)
            cfg = build_config(width=p["width"], height=p["height"], model=ip["model"], steps=ip["steps"], cfg=ip["cfg"],
                               shift=ip["shift"], frames=1, sampler=ip["sampler"], seed_mode=2, seed=seed,
                               strength=ip["strength"] if init else 1.0, loras=ip["loras"], clip_skip=ip["clip_skip"], adv=ip["adv"])
            label = f"Image {i + 1}/{ip['count']}"
            db.update("projects", pid, message=label)
            sp_, sn_ = apply_style(opts["prompts"]["image"] or p["prompt"], opts["prompts"].get("image_negative") or "", opts.get("style", ""))
            frames = _retry_generate(client, pid, label, prompt=sp_, negative=sn_, config=cfg, image=init, cancel_event=ev,
                                     on_progress=lambda st, n, label=label: db.update("projects", pid, message=f"{label} ({st} {n})"))
            frames[0].save(idir / f"img_{i:03d}.png")
        db.update("projects", pid, status="done", message="Done")
    except GenerationCancelled:
        db.update("projects", pid, status="cancelled", message="Cancelled")
    except Exception as e:  # noqa: BLE001
        db.update("projects", pid, status="failed", message=str(e)[:500])
    finally:
        client.close()


EDIT_MODEL_RE = re.compile(r"edit|kontext|klein|flux_?[23]", re.I)   # reference-aware models: the image is context, not a noisy init (strength 1.0)


def run_character_sample(pid: int):
    """Character mode without a reference image: render ONE neutral front-view image. Once the user confirms it,
    run_character uses it as the reference for every image, so the character stays the same."""
    ev = cancel_events.setdefault(pid, threading.Event())
    ev.clear()
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    s = db.get_settings()
    opts = db.project_options(p)
    pdir = project_dir(pid)
    client = client_from(s)
    try:
        ip = image_params(s, opts)
        (pdir / "sample.png").unlink(missing_ok=True)
        desc = (opts["prompts"]["image"] or "").strip().rstrip(" .")
        shot, light, bg = character.variants(1)[0]
        db.update("projects", pid, status="generating", message="Rendering sample image…", video_path=None)
        cfg = build_config(width=p["width"], height=p["height"], model=ip["model"], steps=ip["steps"], cfg=ip["cfg"], shift=ip["shift"],
                           frames=1, sampler=ip["sampler"], seed_mode=2, seed=seed_for(opts, 0), loras=ip["loras"],
                           clip_skip=ip["clip_skip"], adv=ip["adv"])
        prompt, negative = character.build_prompt(desc, shot, light, bg, opts["prompts"].get("image_negative") or "")
        prompt, negative = apply_style(prompt, negative, opts.get("style", ""))
        frames = _retry_generate(client, pid, "Sample image", prompt=prompt, negative=negative, config=cfg, cancel_event=ev,
                                 on_progress=lambda st, k: db.update("projects", pid, message=f"Rendering sample image ({st} {k})"))
        frames[0].save(pdir / "sample.png")
        db.update("projects", pid, status="sample_ready", message="Sample ready: confirm it, or generate another")
    except GenerationCancelled:
        db.update("projects", pid, status="cancelled", message="Cancelled")
    except Exception as e:  # noqa: BLE001
        db.update("projects", pid, status="failed", message=str(e)[:500])
    finally:
        client.close()


def run_character(pid: int):
    """Character mode: render `count` images of ONE character in varied poses / angles / lighting / backgrounds,
    from a text description and/or a reference image, plus a caption per image for LoRA training."""
    ev = cancel_events.setdefault(pid, threading.Event())
    ev.clear()
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    s = db.get_settings()
    opts = db.project_options(p)
    pdir = project_dir(pid)
    client = client_from(s)
    try:
        refs = db.q("SELECT * FROM refs WHERE project_id=? ORDER BY idx", (pid,))
        ip = image_params(s, opts, bool(refs))
        n = int(opts["character"]["count"])
        trigger = (opts["character"].get("trigger") or "").strip()
        desc = (opts["prompts"]["image"] or "").strip().rstrip(" .") or "the same character as in the reference image"
        style = opts.get("style", "")
        idir = pdir / "images"
        shutil.rmtree(idir, ignore_errors=True)
        idir.mkdir()
        init, strength = None, 1.0
        anchor = (pdir / "refs" / refs[0]["filename"]) if refs else (pdir / "sample.png")   # reference image wins over the sample
        if anchor.exists():
            init = encode_image(fit_cover(Image.open(anchor), p["width"], p["height"]), p["width"], p["height"])
            user = opts["image"].get("strength")
            strength = float(user) if user not in (None, "") else (1.0 if EDIT_MODEL_RE.search(ip["model"]) else 0.92)
        elif not refs:
            raise RuntimeError("No confirmed sample image yet: generate and confirm a sample first")
        captions: dict[str, str] = {}
        db.update("projects", pid, status="generating", message="Starting…", video_path=None)
        for i, (shot, light, bg) in enumerate(character.variants(n)):
            if ev.is_set():
                raise GenerationCancelled()
            cfg = build_config(width=p["width"], height=p["height"], model=ip["model"], steps=ip["steps"], cfg=ip["cfg"],
                               shift=ip["shift"], frames=1, sampler=ip["sampler"], seed_mode=2, seed=seed_for(opts, i),
                               strength=strength if init else 1.0, loras=ip["loras"], clip_skip=ip["clip_skip"], adv=ip["adv"])
            label = f"Image {i + 1}/{n}"
            db.update("projects", pid, message=label)
            prompt, negative = character.build_prompt(desc, shot, light, bg, opts["prompts"].get("image_negative") or "")
            prompt, negative = apply_style(prompt, negative, style)
            frames = _retry_generate(client, pid, label, prompt=prompt, negative=negative, config=cfg, image=init, cancel_event=ev,
                                     on_progress=lambda st, k, label=label: db.update("projects", pid, message=f"{label} ({st} {k})"))
            name = f"img_{i:03d}.png"
            frames[0].save(idir / name)
            look = {"realistic": "photo", "cartoon": "cartoon illustration"}.get(style, "")
            captions[name] = ", ".join(x for x in (trigger, look, shot, light, bg) if x)
            (pdir / "captions.json").write_text(json.dumps(captions, indent=1))
        db.update("projects", pid, status="done", message="Done")
    except GenerationCancelled:
        db.update("projects", pid, status="cancelled", message="Cancelled")
    except Exception as e:  # noqa: BLE001
        db.update("projects", pid, status="failed", message=str(e)[:500])
    finally:
        client.close()


def run_generation(pid: int):
    ev = cancel_events.setdefault(pid, threading.Event())
    ev.clear()
    p = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    s = db.get_settings()
    opts = db.project_options(p)
    pdir = project_dir(pid)
    client = client_from(s)
    try:
        db.update("projects", pid, status="generating", message="Starting…")
        refs = db.q("SELECT * FROM refs WHERE project_id=? ORDER BY idx", (pid,))
        chunks = db.q("SELECT * FROM chunks WHERE project_id=? ORDER BY idx", (pid,))
        vp = video_params(s, opts)
        steps = vp["steps"]
        negative = video_negative(s, opts)
        prev_last: Path | None = None
        for ch in chunks:
            if ev.is_set():
                raise GenerationCancelled()
            cdir = pdir / f"chunk_{ch['idx']:03d}"
            vpath, lpath = cdir / "chunk.mp4", cdir / "last.png"
            if ch["status"] == "done" and vpath.exists() and lpath.exists():
                prev_last = lpath
                continue
            cdir.mkdir(exist_ok=True)
            db.update("chunks", ch["id"], status="running", progress=0, error="")
            db.update("projects", pid, message=f"Chunk {ch['idx'] + 1}/{len(chunks)}")

            # ---- start image (None = pure text-to-video, only in video mode without a reference image)
            start_img = None
            if ch["idx"] == 0:
                if refs:
                    start_img = Image.open(pdir / "refs" / refs[0]["filename"])
                elif p["mode"] != "video":
                    kf = pdir / "keyframe.png"
                    if not kf.exists():
                        make_keyframe(client, s, p, opts, opts["prompts"]["image"] or ch["prompt"], kf, ev, seed_for(opts, 0))
                        db.update("projects", pid, message=f"Chunk {ch['idx'] + 1}/{len(chunks)}")
                    start_img = Image.open(kf)
            else:
                start_img = Image.open(prev_last)
            img_bytes, sp = None, None
            if start_img is not None:
                start_img = fit_cover(start_img, p["width"], p["height"])
                sp = cdir / "start.png"
                start_img.save(sp)
                img_bytes = encode_image(start_img, p["width"], p["height"])

            def prog(stage, n, ch=ch):
                if stage in ("sampling", "secondPassSampling"):
                    db.update("chunks", ch["id"], progress=min(0.97, n / max(1, steps)))

            seed = seed_for(opts, ch["idx"])
            db.update("chunks", ch["id"], seed=seed)
            cfg = build_config(
                seed=seed, loras=vp["loras"], width=p["width"], height=p["height"], model=vp["model"], refiner=vp["refiner"],
                refiner_start=vp["refiner_start"], steps=steps, cfg=vp["cfg"], shift=vp["shift"], strength=vp["strength"],
                frames=ch["gen_frames"], sampler=vp["sampler"], seed_mode=2, clip_skip=vp["clip_skip"], adv=vp["adv"])
            vprompt, vneg = apply_style(ch["prompt"], negative, opts.get("style", ""))
            frames = _retry_generate(client, pid, f"Chunk {ch['idx'] + 1}/{len(chunks)}", prompt=vprompt, negative=vneg,
                                     config=cfg, image=img_bytes, on_progress=prog, cancel_event=ev)

            # ---- save frames (skip the duplicated seed frame on continuation chunks) and encode
            fdir = cdir / "frames"
            shutil.rmtree(fdir, ignore_errors=True)
            fdir.mkdir()
            use = frames[1:] if ch["idx"] > 0 else frames
            use = use[:ch["keep_frames"]]
            for i, fr in enumerate(use):
                fr.save(fdir / f"{i:05d}.png")
            video.frames_to_mp4(fdir, vpath, video_timing(opts)[1])
            shutil.rmtree(fdir, ignore_errors=True)
            video.extract_last_frame(vpath, lpath)   # ffmpeg last frame -> next chunk's init image
            prev_last = lpath
            db.update("chunks", ch["id"], status="done", progress=1.0, video_path=str(vpath.relative_to(db.DATA_DIR)),
                      last_frame=str(lpath.relative_to(db.DATA_DIR)), start_image=str(sp.relative_to(db.DATA_DIR)) if sp else None)

        db.update("projects", pid, message="Joining chunks…")
        vids = [db.DATA_DIR / c["video_path"] for c in db.q("SELECT video_path FROM chunks WHERE project_id=? ORDER BY idx", (pid,))]
        final = pdir / "final.mp4"
        video.concat(vids, final)
        db.update("projects", pid, status="done", message="Done", video_path=str(final.relative_to(db.DATA_DIR)))
    except GenerationCancelled:
        db.run("UPDATE chunks SET status='pending', progress=0 WHERE project_id=? AND status='running'", (pid,))
        db.update("projects", pid, status="cancelled", message="Cancelled — resume to continue from the last finished chunk")
    except Exception as e:  # noqa: BLE001
        db.run("UPDATE chunks SET status='failed', error=? WHERE project_id=? AND status='running'", (str(e), pid))
        db.update("projects", pid, status="failed", message=str(e)[:500])
    finally:
        client.close()
