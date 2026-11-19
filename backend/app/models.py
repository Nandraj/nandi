"""Draw Things model catalog: classify installed models and suggest per-model defaults."""
from __future__ import annotations

import json
import re

VIDEO_RE = re.compile(r"wan|ltx|hunyuan|svd|video|cogvideo|mochi|i2v|t2v|ti2v|flf2v|animate|hailuo", re.I)
SKIP_RE = re.compile(r"lora|vae|encoder|clip|controlnet|control_|t5|umt5|ip_adapter|upscal|esrgan|face_restor|embedding|textual|_tae|refiner_lora|moondream|siglip|_vl_|vlm|instruct", re.I)

# (regex, preset). First match wins, so keep specific entries first. These are starting points, not truths.
_P = lambda **k: k  # noqa: E731
PRESETS = [
    (r"wan.*(2\.2|v2\.2).*5b", _P(steps=30, cfg=5.0, shift=5.0, sampler="UniPCTrailing", frames=121, fps=24)),
    (r"wan.*(2\.2|v2\.2).*(hne|lne|a14b)", _P(steps=30, cfg=3.5, shift=5.0, sampler="UniPCTrailing", frames=81, fps=16, refiner_start=0.1)),
    (r"wan", _P(steps=30, cfg=5.0, shift=5.0, sampler="UniPCTrailing", frames=81, fps=16)),
    (r"ltx", _P(steps=30, cfg=3.0, shift=1.0, sampler="EulerATrailing", frames=97, fps=24)),
    (r"hunyuan.*video|hunyuan_video", _P(steps=30, cfg=1.0, shift=7.0, sampler="DPMPP2MTrailing", frames=129, fps=24)),
    (r"svd", _P(steps=25, cfg=2.5, shift=1.0, sampler="EulerATrailing", frames=25, fps=8)),
    (r"cogvideo|mochi", _P(steps=50, cfg=6.0, shift=1.0, sampler="DDIMTrailing", frames=49, fps=8)),
    (r"flux.*schnell", _P(steps=4, cfg=1.0, shift=1.0, sampler="EulerATrailing")),
    (r"flux", _P(steps=20, cfg=3.5, shift=1.0, sampler="DPMPP2MTrailing")),
    (r"z_image.*turbo", _P(steps=8, cfg=1.0, shift=3.0, sampler="EulerATrailing")),
    (r"z_image", _P(steps=30, cfg=4.0, shift=3.0, sampler="EulerATrailing")),
    (r"qwen_image|qwen-image", _P(steps=20, cfg=4.0, shift=3.0, sampler="EulerATrailing")),
    (r"hidream", _P(steps=30, cfg=5.0, shift=3.0, sampler="EulerATrailing")),
    (r"sd3", _P(steps=28, cfg=4.5, shift=3.0, sampler="DPMPP2MTrailing")),
    (r"sdxl|xl_", _P(steps=30, cfg=7.0, shift=1.0, sampler="DPMPP2MKarras")),
    (r"sd_v1|v1\.5|v1_5|sd15|stable_diffusion", _P(steps=25, cfg=7.5, shift=1.0, sampler="DPMPP2MKarras")),
]
FALLBACK = _P(steps=20, cfg=5.0, shift=1.0, sampler="DPMPP2MKarras")


def is_video(text: str) -> bool:
    return bool(VIDEO_RE.search(text))


def preset_for(file: str, version: str = "", available: set | None = None) -> dict:
    t = f"{file} {version}".lower()
    out = dict(FALLBACK)
    for pat, p in PRESETS:
        if re.search(pat, t):
            out = dict(p)
            break
    if "hne" in t:   # Wan 2.2 high-noise expert: pair it with its low-noise expert if that file is installed
        low = re.sub("hne", "lne", file, flags=re.I)
        if available is None or low in available:
            out["refiner"] = low
    return out


def parse_models(blob: bytes, files: list[str]) -> list[dict]:
    """Echo.override.models is a JSON array of {name, file, version, ...}; fall back to the raw file list."""
    items: dict[str, dict] = {}
    try:
        for m in json.loads(blob.decode() or "[]"):
            if isinstance(m, dict) and m.get("file"):
                items[m["file"]] = {"file": m["file"], "name": m.get("name") or m["file"], "version": str(m.get("version") or "")}
    except Exception:  # noqa: BLE001
        pass
    for f in files:
        if f.endswith(".ckpt") and f not in items and not SKIP_RE.search(f):
            items[f] = {"file": f, "name": f, "version": ""}
    return list(items.values())


def classify(models: list[dict]) -> list[dict]:
    avail = {m["file"] for m in models}
    out = []
    for m in models:
        if SKIP_RE.search(m["file"]) and not VIDEO_RE.search(m["file"]):
            continue
        t = f"{m['file']} {m['version']}"
        out.append({**m, "kind": "video" if is_video(t) else "image", "preset": preset_for(m["file"], m["version"], avail)})
    return sorted(out, key=lambda m: m["name"].lower())


def parse_simple_list(blob: bytes) -> list[dict]:
    out = []
    try:
        for m in json.loads(blob.decode() or "[]"):
            if isinstance(m, dict) and m.get("file"):
                out.append({"file": m["file"], "name": m.get("name") or m["file"]})
    except Exception:  # noqa: BLE001
        pass
    return sorted(out, key=lambda m: m["name"].lower())
