"""Character dataset planning: the poses / angles / lighting / backgrounds that make a good LoRA training set.

A character LoRA learns identity best from ~15-40 images where ONLY the pose, camera angle, framing, expression,
lighting and background change while the face, hair, body and outfit stay the same. Each image gets a caption that
describes just what varies (the identity itself is meant to be absorbed by the trigger word).
"""
from __future__ import annotations

# (framing + pose + camera angle). The first entries cover the core views a LoRA needs: front / 3-4 / profile / back,
# close-up / medium / full body.
SHOTS = [
    "full body shot, standing, front view, neutral relaxed pose",
    "close-up portrait, front view, neutral expression",
    "full body shot, three-quarter view, standing",
    "close-up portrait, three-quarter view, slight smile",
    "full body shot, side profile view, walking",
    "close-up portrait, side profile",
    "full body shot, back view, looking over the shoulder",
    "medium shot, waist up, front view, hands visible",
    "head and shoulders, looking up, low angle",
    "head and shoulders, looking down, high angle",
    "cowboy shot, mid-thigh up, hands on hips, confident stance",
    "full body, sitting on a chair, relaxed",
    "full body, running, dynamic motion",
    "medium shot, laughing, head tilted",
    "medium shot, arms crossed, three-quarter view",
    "full body, crouching, low angle",
    "medium shot, serious expression, looking away from the camera",
    "full body, walking toward the camera",
    "waist up, waving at the camera",
    "full body, three-quarter back view, walking away",
    "close-up, surprised expression",
    "close-up, angry expression",
    "medium shot, leaning against a wall",
    "full body, kneeling",
    "over-the-shoulder shot from behind, head turned toward the camera",
    "bust shot, arms raised, dramatic pose",
    "full body, jumping mid-air",
    "medium shot, eyes closed, calm expression",
    "full body, high angle looking down at the character",
    "full body, hero pose, slight dutch angle",
]

LIGHTS = [
    "soft natural daylight", "golden hour warm sunlight", "overcast diffuse light", "studio softbox lighting",
    "dramatic rim light", "neon night lighting", "warm indoor lamp light", "harsh midday sun",
]

BACKGROUNDS = [
    "plain light gray studio backdrop", "city street", "park with trees", "cozy living room interior",
    "sandy beach", "modern office", "forest path", "plain white background",
]


def variants(n: int) -> list[tuple[str, str, str]]:
    """-> n distinct-looking (shot, lighting, background) combinations; consecutive images never repeat a pose."""
    out = []
    for i in range(n):
        out.append((SHOTS[i % len(SHOTS)], LIGHTS[(i * 3) % len(LIGHTS)], BACKGROUNDS[(i * 5 + i // len(BACKGROUNDS)) % len(BACKGROUNDS)]))
    return out


FULL_BODY_NEG = "cropped, cut off, out of frame, close-up, headshot, portrait, missing legs, missing feet, cut off feet, cut off head, partial body"


def is_full_body(shot: str) -> bool:
    return shot.startswith("full body")


def build_prompt(desc: str, shot: str, light: str, bg: str, negative: str) -> tuple[str, str]:
    """Framing goes FIRST so the model doesn't default to a portrait; full-body shots also forbid cropping."""
    if is_full_body(shot):
        frame = f"Full body shot of a character, entire body visible from head to toe including feet and shoes, centered with space around, {shot.split(', ', 1)[-1]}"
        negative = f"{negative.rstrip(' ,')}, {FULL_BODY_NEG}" if negative.strip() else FULL_BODY_NEG
    else:
        frame = shot[0].upper() + shot[1:]
    return f"{frame}. {desc}. {light}, {bg}. Solo, a single character, sharp focus.", negative
