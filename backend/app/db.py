"""SQLite persistence (stdlib sqlite3)."""
from __future__ import annotations
import json
import sqlite3
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "nandi.db"
_LEGACY_DB = DATA_DIR / "mvgen.db"          # name used before the project was called Nandi
if _LEGACY_DB.exists() and not DB_PATH.exists():
    DB_PATH = _LEGACY_DB                      # keep using existing data instead of silently starting empty
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, kind TEXT NOT NULL, prompt TEXT NOT NULL,
  duration INTEGER NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft', message TEXT DEFAULT '',
  script TEXT, video_path TEXT, created REAL, updated REAL
);
CREATE TABLE IF NOT EXISTS refs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL, filename TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL, prompt TEXT NOT NULL, scene_idx INTEGER,
  gen_frames INTEGER NOT NULL, keep_frames INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', progress REAL DEFAULT 0, error TEXT DEFAULT '',
  video_path TEXT, last_frame TEXT, start_image TEXT
);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.c = c
    return c


def _add_column(table: str, col: str, decl: str):
    cols = [r["name"] for r in conn().execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn().execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init():
    conn().executescript(SCHEMA)
    _add_column("projects", "options", "TEXT")   # per-project: seed, loras
    _add_column("projects", "mode", "TEXT NOT NULL DEFAULT 'script'")   # script | image | video | t2v
    _add_column("chunks", "seed", "INTEGER")
    conn().commit()
    for old, new in (("ollama_url", "llm_base_url"), ("ollama_model", "llm_model")):   # settings key rename
        if one("SELECT 1 FROM settings WHERE key=?", (old,)) and not one("SELECT 1 FROM settings WHERE key=?", (new,)):
            run("UPDATE settings SET key=? WHERE key=?", (new, old))


EMPTY_LORA = {"file": "", "weight": 1.0, "mode": "all"}
DEFAULT_OPTIONS = {
    "seed_mode": "random",     # random | fixed | increment
    "seed": 0,
    "loras": [dict(EMPTY_LORA), dict(EMPTY_LORA)],            # video LoRAs (the two fixed slots, e.g. Lightning high/low)
    "extra_loras": [],                                        # any number more (character LoRAs…), applied after the two above
    "character": {"count": 20, "trigger": ""},                # character-dataset mode: number of images, caption trigger word
    # Per-project prompts. None = fall back to the script prompts / Settings negative prompt.
    "prompts": {"image": "", "image_negative": "", "video": "", "video_negative": None},
    # Model parameters; missing keys fall back to Settings. image.loras / image.count / video.frames / video.fps are extras.
    "image": {},
    "video": {},
    "style": "",               # "" = leave prompts alone | realistic | cartoon
}


def project_options(p: dict) -> dict:
    o = json.loads(p["options"]) if p.get("options") else {}
    out = {**DEFAULT_OPTIONS, **o}
    out["prompts"] = {**DEFAULT_OPTIONS["prompts"], **(o.get("prompts") or {})}
    out["image"] = dict(o.get("image") or {})
    out["video"] = dict(o.get("video") or {})
    out["extra_loras"] = list(o.get("extra_loras") or [])
    out["character"] = {**DEFAULT_OPTIONS["character"], **(o.get("character") or {})}
    ls = list(out["loras"])[:2]
    while len(ls) < 2:
        ls.append(dict(EMPTY_LORA))
    out["loras"] = ls
    return out


def q(sql: str, args=()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql: str, args=()):
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


def run(sql: str, args=()) -> int:
    cur = conn().execute(sql, args)
    conn().commit()
    return cur.lastrowid


def update(table: str, id_: int, **fields):
    if table == "projects":
        fields["updated"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    run(f"UPDATE {table} SET {cols} WHERE id=?", (*fields.values(), id_))


# ---- settings -------------------------------------------------------------
DEFAULT_SETTINGS = {
    "llm_provider": "ollama",       # ollama | openai (any OpenAI-compatible API) | anthropic
    "llm_base_url": "http://localhost:11434",
    "llm_model": "qwen3.5:2b",
    "llm_api_key": "",
    "dt_host": "127.0.0.1",
    "dt_port": 7859,
    "dt_tls": True,
    "dt_secret": "",
    "seed_mode": "random",          # default for new projects: random | fixed | increment
    "seed": 0,
    "loras": None,                  # None = auto-pick the Wan 2.2 Lightning high/low-noise pair if downloaded; [] = none
    "lightning_steps": 6,           # used instead of "steps"/"cfg" when a *lightning* LoRA is active
    "lightning_cfg": 1.0,
    "dt_models_dir": "~/Library/Containers/com.liuliu.draw-things/Data/Documents/Models",
    "hne_model": "wan_v2.2_a14b_hne_i2v_q8p.ckpt",
    "lne_model": "wan_v2.2_a14b_lne_i2v_q8p.ckpt",
    "refiner_start": 0.1,
    "steps": 30,
    "cfg": 3.5,
    "shift": 5.0,
    "sampler": "UniPCTrailing",
    "negative_prompt": "bright tones, overexposed, static, blurred details, subtitles, style, works, paintings, images, static, overall gray, worst quality, low quality, JPEG compression residue, ugly, incomplete, extra fingers, poorly drawn hands, poorly drawn faces, deformed, disfigured, misshapen limbs, fused fingers, still picture, messy background, three legs, many people in the background, walking backwards",
    "keyframe_model": "z_image_turbo_1.0_q8p.ckpt",
    "keyframe_steps": 8,
    "keyframe_cfg": 1.0,
    "keyframe_shift": 3.0,
    "keyframe_sampler": "EulerATrailing",
}


def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    for r in q("SELECT key, value FROM settings"):
        if r["key"] in s:
            s[r["key"]] = json.loads(r["value"])
    return s


SECRET_KEYS = ("llm_api_key", "dt_secret")
MASK = "********"


def public_settings() -> dict:
    """Settings for the browser: secrets are never sent back, only a mask when one is set."""
    s = get_settings()
    for k in SECRET_KEYS:
        if s[k]:
            s[k] = MASK
    return s


def save_settings(new: dict):
    for k, v in new.items():
        if k in SECRET_KEYS and v == MASK:      # unchanged secret
            continue
        if k in DEFAULT_SETTINGS:
            run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, json.dumps(v)))
