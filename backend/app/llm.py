"""Script writer / prompt enhancer. Works with Ollama, any OpenAI-compatible API, or Anthropic."""
from __future__ import annotations
import base64
import json
import math
import re
from pathlib import Path

import httpx

SCENE_SECONDS = 5  # one scene ~ one 81-frame chunk @16fps

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "style": {"type": "string", "description": "Overall visual style, camera and lighting language"},
        "characters": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
            "required": ["name", "description"]}},
        "scenes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string", "description": "What happens, narrative beat"},
                "location": {"type": "string", "description": "Short name of the single place this scene happens, e.g. 'market square'. Reuse the exact same name when consecutive scenes share a place."},
                "visual_prompt": {"type": "string", "description": "Plain-prose video prompt, 40-70 words: who (with appearance), ONE continuous action, setting, ONE camera move, lighting. No scene headings, no brackets, no cuts."},
                "duration_sec": {"type": "number"},
            },
            "required": ["title", "summary", "location", "visual_prompt", "duration_sec"]}},
    },
    "required": ["title", "logline", "style", "characters", "scenes"],
}

SYSTEM = (
    "You are a film director writing a shot list for an AI image-to-video generator (Wan 2.2). "
    "The whole film is ONE unbroken take cut into ~5 second scenes: the first frame of each scene is exactly the last "
    "frame of the previous scene, and the generator can only animate what is already in its start frame. "
    "It cannot cut, teleport, or change location mid-shot. Rules:\n"
    "- One scene = one simple action beat and one camera move (slow push-in, gentle pan, tracking, or static).\n"
    "- Each scene must END visibly different from how it starts (a character moves somewhere, an object changes hands, "
    "the camera travels). Never return to the starting pose or position.\n"
    "- Never write montages, 'quick cuts', multiple angles, or several sequential actions; split them into separate scenes.\n"
    "- Continuity: scene N starts where scene N-1 ended. To change place, show the journey in the shot (characters walk "
    "or fly there while the camera follows) over one or more scenes; never jump to a new place. "
    "Set each scene's `location` field to where the scene ends up.\n"
    "- visual_prompt is plain descriptive prose of 40-70 words. Write out the characters' appearance in full every time "
    "(never 'same appearance' or 'as before'). No scene headings (EXT./INT.), no brackets or parentheses, "
    "no references to other scenes, no dialogue, no text on screen.\n"
    "- Stay faithful to the user's brief; do not add plot events it does not mention."
)


def build_user_prompt(p: dict, n_scenes: int, feedback: str = "", previous: dict | None = None, n_refs: int = 0) -> str:
    kind = "short clip" if p["kind"] == "clip" else "movie"
    s = (f"Write the script for a {kind}.\nTotal duration: {p['duration']} seconds.\n"
         f"Number of scenes: exactly {n_scenes} (about {SCENE_SECONDS} seconds each; durations must sum to {p['duration']}).\n"
         f"Idea / brief: {p['prompt']}\n")
    look = {"realistic": "Look: realistic / live-action. Describe real people, places and photographic lighting; no cartoon or animation wording.",
            "cartoon": "Look: animated cartoon. Describe stylized animated characters and settings; no photorealistic wording."}.get(p.get("style", ""))
    if look:
        s += look + "\n"
    if n_refs:
        s += f"{n_refs} reference image(s) are attached: keep characters, setting and look consistent with them.\n"
    if previous and feedback:
        s += f"\nPrevious draft:\n{json.dumps(previous, ensure_ascii=False)}\n\nRevise it according to this feedback: {feedback}\n"
    return s


def clean_prompt(text: str) -> str:
    """Strip screenplay artefacts the video model cannot use."""
    text = re.sub(r"\((?:[^)]*(?:continu|seamless|previous|same)[^)]*)\)", "", text, flags=re.I)
    text = re.sub(r"^\s*(?:EXT|INT)\.?[A-Z'\u2019 /.]*?\s*(?:-|\u2014)\s*[A-Z ]+\.\s*", "", text or "")   # 'EXT. PLACE / INT. PLACE - DAY.'
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\b(Camera|Lighting):\s*", "", text)
    text = re.sub(r"\s+([.,])", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def normalize(script: dict, total: int, n_scenes: int) -> dict:
    scenes = script.get("scenes") or []
    if len(scenes) > n_scenes:
        scenes = scenes[:n_scenes]
    for s in scenes:
        s["visual_prompt"] = clean_prompt(s.get("visual_prompt", ""))
        s["location"] = (s.get("location") or "").strip()
        s["duration_sec"] = max(1.0, float(s.get("duration_sec") or SCENE_SECONDS))
    tot = sum(s["duration_sec"] for s in scenes) or 1
    for s in scenes:
        s["duration_sec"] = round(s["duration_sec"] * total / tot, 2)
    script["scenes"] = scenes
    return script


def _root(url: str, provider: str) -> str:
    """Normalize a user-entered base URL to the API root for the provider."""
    u = url.strip().rstrip("/")
    if provider == "ollama":
        return re.sub(r"/(v1|api)$", "", u)
    if provider == "anthropic":
        return re.sub(r"/v1$", "", u)
    # OpenAI-compatible: keep versioned roots (…/v1, …/api/v1, …/v1beta/openai), otherwise add /v1
    return u if re.search(r"/(v\d+\w*|openai)(/|$)", u) else u + "/v1"


def _is_local(url: str) -> bool:
    return bool(re.match(r"https?://(localhost|127\.|0\.0\.0\.0|192\.168\.|10\.|\[::1\])", url.strip()))


def _headers(settings: dict) -> dict:
    key = settings.get("llm_api_key", "")
    if settings["llm_provider"] == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    h = {"content-type": "application/json"}
    if key:
        h["authorization"] = f"Bearer {key}"
    return h


def list_models(settings: dict) -> list:
    prov, root = settings["llm_provider"], _root(settings["llm_base_url"], settings["llm_provider"])
    with httpx.Client(timeout=8) as c:
        if prov == "ollama":
            r = c.get(root + "/api/tags", headers=_headers(settings))
        else:
            r = c.get(root + ("/v1/models" if prov == "anthropic" else "/models"), headers=_headers(settings))
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
        data = r.json()
    if prov == "ollama":
        return [m["name"] for m in data.get("models", [])]
    return [m.get("id") or m.get("name") for m in data.get("data", data.get("models", [])) if isinstance(m, dict)]


def _clean(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _mime(b64: str) -> str:
    head = base64.b64decode(b64[:16] + "=" * (-len(b64[:16]) % 4))
    return "image/png" if head.startswith(b"\x89PNG") else "image/webp" if head[8:12] == b"WEBP" else "image/jpeg"


JSON_NOTE = "\n\nReply with ONLY a single JSON object (no markdown) with keys: title, logline, style, characters[{name,description}], scenes[{title,summary,visual_prompt,duration_sec}]."


def _post(c: httpx.Client, url: str, headers: dict, body: dict) -> httpx.Response:
    return c.post(url, headers=headers, json=body)


def _chat_ollama(settings: dict, system: str, user_text: str, images: list, schema: dict = SCHEMA, note: str = JSON_NOTE) -> str:
    root = _root(settings["llm_base_url"], "ollama")
    with httpx.Client(timeout=httpx.Timeout(900, connect=10)) as c:
        for use_images in ([True, False] if images else [False]):
            user = {"role": "user", "content": user_text}
            if use_images:
                user["images"] = images
            body = {"model": settings["llm_model"], "messages": [{"role": "system", "content": system}, user],
                    "stream": False, "think": False, "format": schema, "options": {"temperature": 0.7, "num_ctx": 8192}}
            r = _post(c, root + "/api/chat", _headers(settings), body)
            if r.status_code < 400:
                return r.json()["message"]["content"]
        raise RuntimeError(f"LLM server error {r.status_code}: {r.text[:300]}")


def _chat_openai(settings: dict, system: str, user_text: str, images: list, schema: dict = SCHEMA, note: str = JSON_NOTE) -> str:
    """Any OpenAI-compatible /chat/completions API. Degrades gracefully when a provider rejects options."""
    url = _root(settings["llm_base_url"], "openai") + "/chat/completions"
    local = _is_local(settings["llm_base_url"])
    formats = [{"type": "json_schema", "json_schema": {"name": "script", "strict": True, "schema": schema}},
               {"type": "json_object"}, None]
    last = None
    with httpx.Client(timeout=httpx.Timeout(1800, connect=10)) as c:
        for use_images in ([True, False] if images else [False]):
            for rf in formats:
                text = user_text + (note if rf is not formats[0] else "")
                content = text if not use_images else (
                    [{"type": "text", "text": text}] +
                    [{"type": "image_url", "image_url": {"url": f"data:{_mime(i)};base64,{i}"}} for i in images])
                body = {"model": settings["llm_model"], "stream": False,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
                if rf:
                    body["response_format"] = rf
                if local:   # local servers (llama.cpp, LM Studio…) accept these; hosted APIs may reject unknown params
                    body["temperature"] = 0.7
                    body["chat_template_kwargs"] = {"enable_thinking": False}
                r = _post(c, url, _headers(settings), body)
                if r.status_code < 400:
                    return r.json()["choices"][0]["message"].get("content") or ""
                last = r
                if r.status_code in (401, 403, 404):    # auth / wrong URL or model: retrying won't help
                    raise RuntimeError(f"LLM server error {r.status_code}: {r.text[:300]}")
    raise RuntimeError(f"LLM server error {last.status_code}: {last.text[:300]}")


def _chat_anthropic(settings: dict, system: str, user_text: str, images: list, schema: dict = SCHEMA, note: str = JSON_NOTE) -> str:
    url = _root(settings["llm_base_url"], "anthropic") + "/v1/messages"
    last = None
    with httpx.Client(timeout=httpx.Timeout(900, connect=10)) as c:
        for use_images in ([True, False] if images else [False]):
            content = ([{"type": "image", "source": {"type": "base64", "media_type": _mime(i), "data": i}} for i in images]
                       if use_images else []) + [{"type": "text", "text": user_text}]
            body = {"model": settings["llm_model"], "max_tokens": 8192, "system": system,
                    "messages": [{"role": "user", "content": content}],
                    "tools": [{"name": "submit_script", "description": "Submit the finished script.", "input_schema": schema}],
                    "tool_choice": {"type": "tool", "name": "submit_script"}}
            r = _post(c, url, _headers(settings), body)
            if r.status_code < 400:
                for blk in r.json().get("content", []):
                    if blk.get("type") == "tool_use":
                        return json.dumps(blk["input"])
                raise RuntimeError("The model did not return a script.")
            last = r
            if r.status_code in (401, 403, 404):
                break
    raise RuntimeError(f"LLM server error {last.status_code}: {last.text[:300]}")


BAD_PATTERNS = re.compile(r"montage|quick cuts?|cuts? to|split[- ]screen|\bfirst,|\bnext,|\bfinally,|\bthen\b|\bafter that\b|\bbefore\b.*\bagain\b|returns? to (?:her|his|its|the) (?:original|starting)|same appearance|as before|previous scene", re.I)
MAX_WORDS = 100


def lint_scenes(script: dict) -> list[str]:
    issues = []
    for i, s in enumerate(script.get("scenes") or [], 1):
        vp = s.get("visual_prompt", "")
        n = len(vp.split())
        if n > MAX_WORDS:
            issues.append(f"Scene {i}: visual_prompt is {n} words; keep it to 40-70.")
        if BAD_PATTERNS.search(vp):
            issues.append(f"Scene {i}: contains a montage / multiple sequential actions / cross-scene reference; use ONE action in ONE continuous shot.")
        if not (s.get("location") or "").strip():
            issues.append(f"Scene {i}: missing location.")
    return issues


def _parse(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)   # tolerate prose around the JSON
        if not m:
            raise RuntimeError(f"The model did not return valid JSON: {text[:200]}")
        return json.loads(m.group(0))


def generate_script(settings: dict, p: dict, ref_paths: list[Path], feedback: str = "", previous: dict | None = None) -> dict:
    n_scenes = max(1, math.ceil(p["duration"] / SCENE_SECONDS))
    images = [base64.b64encode(Path(r).read_bytes()).decode() for r in ref_paths[:4]]
    chat = {"openai": _chat_openai, "anthropic": _chat_anthropic}.get(settings["llm_provider"], _chat_ollama)

    def ask(fb: str, prev: dict | None) -> dict:
        text = _clean(chat(settings, SYSTEM, build_user_prompt(p, n_scenes, fb, prev, len(images)), images))
        if not text:
            raise RuntimeError("The model returned an empty answer (it may have spent its whole budget thinking).")
        return normalize(_parse(text), p["duration"], n_scenes)

    script = ask(feedback, previous)
    issues = lint_scenes(script)
    for _ in range(2):   # self-repair: the video model cannot render montages or overloaded scenes
        if not issues:
            break
        try:
            fixed = ask((feedback + "\n" if feedback else "") + "Fix these problems and keep everything else: " + " ".join(issues), script)
        except RuntimeError:
            break
        if len(lint_scenes(fixed)) <= len(issues):
            script, issues = fixed, lint_scenes(fixed)
    for s in script.get("scenes", []):   # hard cap: overlong prompts get truncated by the text encoder
        w = s["visual_prompt"].split()
        if len(w) > MAX_WORDS:
            cut = " ".join(w[:MAX_WORDS])
            s["visual_prompt"] = cut[: cut.rfind(".") + 1] or cut
    return script


ENHANCE_SCHEMA = {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}
ENHANCE_NOTE = '\n\nReply with ONLY a single JSON object (no markdown): {"prompt": "<the rewritten prompt>"}.'
ENHANCE_SYSTEM = {
    "image": "You rewrite text-to-image prompts. Keep the user's subject and intent, add concrete visual detail "
             "(subject appearance, setting, composition, lens, lighting, style). One paragraph of 40-80 words, no lists, no quotes.",
    "video": "You rewrite prompts for an AI video generator. Keep the user's subject and intent. Describe ONE continuous action, "
             "the setting, ONE camera move and the lighting in plain prose, 40-70 words. No cuts, no scene headings, no brackets, no dialogue.",
    "character": "You rewrite a character description for an AI image generator that will make a LoRA training set of this character. "
                 "Keep the user's character and intent and describe ONLY fixed identity details, concretely: age, gender, ethnicity or species, "
                 "face shape, eyes, nose, lips, hair (colour, length, style), skin tone, body build, height impression, the signature outfit "
                 "(garments, colours, materials), accessories and distinguishing marks. Do NOT mention pose, camera angle, framing, expression, "
                 "lighting or background; those are varied separately. One paragraph of 50-90 words, no lists, no quotes.",
}


def enhance_prompt(settings: dict, text: str, kind: str) -> str:
    chat = {"openai": _chat_openai, "anthropic": _chat_anthropic}.get(settings["llm_provider"], _chat_ollama)
    out = _clean(chat(settings, ENHANCE_SYSTEM.get(kind, ENHANCE_SYSTEM["image"]), f"Prompt to rewrite:\n{text}", [],
                      ENHANCE_SCHEMA, ENHANCE_NOTE))
    if not out:
        raise RuntimeError("The model returned an empty answer.")
    return str(_parse(out).get("prompt", "")).strip() or text
