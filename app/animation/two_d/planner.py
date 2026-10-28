"""Storyboard + casting -> a render plan (plain JSON) for the 2D puppet renderer (Milestone 6).

Missing pictures are reported as plan warnings; rendering refuses them (no stand-in figure / plain sky).

The plan is deterministic: same storyboard + same casting versions -> same plan -> same checksum, so finished scenes
are reused after a restart. Nothing here needs AI.

Timing: until Milestone 8 adds voices, each spoken line gets an estimated time from its word count.
"""
from __future__ import annotations

import io
import re
from typing import TYPE_CHECKING, Any

from PIL import Image

from app.animation.two_d import puppet
from app.core.errors import Conflict

if TYPE_CHECKING:
    from app.container import Hub

WORDS_PER_SEC = 2.4
MIN_LINE, GAP, MAX_SCENE = 1.3, 0.25, 45.0
QUALITY = {"preview": {"short": 360, "fps": 12, "crf": 28}, "final": {"short": 1080, "fps": 0, "crf": 21}}

EMOTION_WORDS = {
    "happy": ("khush", "happy", "hans", "muskura", "excited", "खुश", "हँस", "हंस", "मुस्कु", "उत्साह"),
    "sad": ("dukh", "sad", "udaas", " ro ", " rote", " rona", "दुख", "उदास", " रो"),
    "angry": ("guss", "angry", "naraz", "गुस्स", "नाराज"),
    "scared": (" dar", "darr", "scared", "ghabra", "डर", "घबरा"),
    "surprised": ("hairan", "surprise", "chauk", "shock", "हैरान", "चौंक"),
}
ACTION_WORDS = {
    "wave": ("haath hila", "wave", "हाथ हिला"), "jump": ("kood", "jump", "उछल", "कूद"),
    "nod": ("sir hila", "nod", "सिर हिला"), "point": ("ishara", "point", "इशारा"), "shake": ("kaanp", "shake", "काँप", "कांप"),
}


def _match(text: str, table: dict[str, tuple[str, ...]]) -> str:
    t = f" {(text or '').lower()} "
    for key, words in table.items():
        if any(w in t for w in words):
            return key
    return ""


def emotion_of(direction: str) -> str:
    return _match(direction, EMOTION_WORDS)


def action_of(direction: str) -> str:
    return _match(direction, ACTION_WORDS)


def mood_of(lighting: str, place: str) -> str:
    l, p = (lighting or "").lower(), (place or "").lower()
    if "night" in l or "moon" in l:
        return "night"
    if "sunset" in l or "evening" in l:
        return "sunset"
    if any(w in p for w in ("ghar", "kamra", "class", "andar", "room", "school", "घर", "कमर", "कक्षा", "अंदर")):
        return "indoor"
    return "day"


def camera_of(movement: str) -> str:
    m = (movement or "").lower()
    if "zoom in" in m:
        return "zoom_in"
    if "zoom out" in m:
        return "zoom_out"
    if "pan left" in m:
        return "pan_left"
    if "pan right" in m or "follow" in m:
        return "pan_right"
    return "static"


def place_role(env_ref: str) -> str:
    return (env_ref or "").split(",")[0].strip()


def frame_size(aspect: str, short: int) -> tuple[int, int]:
    long = int(round(short * 16 / 9 / 2)) * 2
    if aspect == "9:16":
        return short, long
    if aspect == "1:1":
        return short, short
    return long, short


def line_seconds(text: str) -> float:
    words = len(re.findall(r"\S+", text or ""))
    return round(max(MIN_LINE, words / WORDS_PER_SEC + 0.3), 2)


def build(hub: "Hub", project_id: int, quality: str = "preview") -> dict[str, Any]:
    """Return {'scenes': [...], 'width', 'height', 'fps', 'warnings': [...], ...}. Raises Conflict if nothing to render."""
    if quality not in QUALITY:
        quality = "preview"
    p = hub.projects.get_project(project_id)
    scenes = hub.storyboards.scenes(project_id)
    if not scenes:
        raise Conflict("Pehle Storyboard banao (Script approve karke 🎞 Storyboard me draft banao).")
    st = hub.storyboards.state(project_id).get("status", "none")
    q = QUALITY[quality]
    s = p["settings"]
    short = min(q["short"], 720) if quality == "final" and s.get("resolution") == "720p" else q["short"]
    w, h = frame_size(s.get("aspect", "16:9"), short)
    fps = q["fps"] or int(s.get("fps") or 30)
    cast = hub.library.casting(project_id)
    lib = hub.library
    warnings: list[str] = []
    missing_roles: set[str] = set()

    def files_of(role: str, kind: str) -> dict | None:
        c = cast.get(role)
        if not c or c["kind"] != kind:
            return None
        it = lib.get(c["item_id"], c["version"])
        return {"item_id": it["id"], "version": it["version"], "name": it["name"], "files": it["files"]}

    seen_actor: set[str] = set()
    out_scenes = []
    for idx, sc in enumerate(scenes):
        cam = sc.get("camera") or {}
        place = place_role(sc.get("environment_ref", ""))
        mood = mood_of(cam.get("lighting", ""), place)
        env = files_of(place, "environment") if place else None
        bg: dict[str, Any] = {"place": place}
        if env:
            role = "background:night" if mood == "night" and "background:night" in env["files"] else "background"
            if role in env["files"]:
                bg.update(path=env["files"][role]["path"], sha=env["files"][role]["sha256"], item=env["item_id"], version=env["version"])
                if role == "background:night":
                    mood = "day"  # night picture already dark: no extra grading
        if "path" not in bg and place and place not in missing_roles:
            missing_roles.add(place)
            warnings.append(f"🏞 '{place}' ki jagah (background) ki image nahi hai.")
        names = [n for n in sc.get("characters", []) if "arrat" not in n.lower() and n.strip()][:4]
        actors = []
        pos = puppet.layout(len(names))
        for i, name in enumerate(names):
            ch = files_of(name, "character")
            a: dict[str, Any] = {"id": name, "x": pos[i], "size": "small" if len(names) >= 3 else "medium"}
            if ch and "main" in ch["files"]:
                a.update(item=ch["item_id"], version=ch["version"], main=ch["files"]["main"]["path"], sha=ch["files"]["main"]["sha256"],
                         variants={k.split(":", 1)[1]: v["path"] for k, v in ch["files"].items()
                                   if (k.startswith("expr:") or k.startswith("pose:")) and ":original" not in k})
            elif name not in missing_roles:
                missing_roles.add(name)
                warnings.append(f"🧍 '{name}' ki image nahi hai.")
            if name not in seen_actor:
                a["enter"] = "left" if pos[i] <= 0.5 else "right"
                seen_actor.add(name)
            actors.append(a)
        t = 1.2 if any(a.get("enter") for a in actors) else 0.5
        talks = []
        for ln in sc.get("dialogue", []):
            if ln.get("kind") == "action" or not (ln.get("text") or "").strip():
                continue
            d = line_seconds(ln["text"])
            spk = ln.get("speaker") or ""
            if ln.get("kind") == "dialogue" and spk in names:
                direction = ln.get("direction") or (cam.get("emotions") or {}).get(spk, "")
                talks.append({"actor": spk, "start": round(t, 3), "end": round(t + d, 3), "emotion": emotion_of(direction),
                              "action": action_of(direction)})
            t += d + GAP
        duration = round(min(MAX_SCENE, max(float(sc.get("duration_seconds") or 0), t + 0.5, 2.0)), 2)
        trans = (cam.get("transition") or "cut").lower()
        out_scenes.append({"n": idx + 1, "scene_id": sc["id"], "background": bg, "actors": actors, "talks": talks, "duration": duration,
                           "camera": camera_of(cam.get("movement", "")), "mood": mood,
                           "fade": trans in ("fade", "dissolve") or idx in (0, len(scenes) - 1)})
    return {"project_id": project_id, "quality": quality, "width": w, "height": h, "fps": fps, "crf": q["crf"],
            "storyboard_status": st, "scenes": out_scenes, "warnings": warnings,
            "seconds": round(sum(x["duration"] for x in out_scenes), 1)}


# ------------------------------------------------------------------ plan -> renderer objects
def load_scene(hub: "Hub", sc: dict, fps: int = 25) -> puppet.PuppetScene:
    data_dir = hub.settings.data_dir

    def img(rel: str) -> Image.Image:
        from app.storage.files import safe_join

        return Image.open(io.BytesIO(safe_join(data_dir, *rel.split("/")).read_bytes()))

    # No stand-ins: a scene without its real background / character pictures is never rendered.
    missing = ([f"jagah '{sc['background'].get('place') or '?'}'"] if not sc["background"].get("path") else []) + \
              [f"'{a['id']}'" for a in sc["actors"] if not a.get("main")]
    if missing:
        raise Conflict(f"Scene {sc.get('n', '?')} nahi banega — image nahi hai: {', '.join(missing)}.")
    bg = img(sc["background"]["path"]).convert("RGB")
    actors = []
    for a in sc["actors"]:
        sprite = img(a["main"]).convert("RGBA")
        variants = {k: img(v).convert("RGBA") for k, v in (a.get("variants") or {}).items()}
        actors.append(puppet.Actor(id=a["id"], sprite=sprite, size=a.get("size", "medium"), x=a["x"], enter=a.get("enter"),
                                   variants=variants))
    talks = [puppet.Talk(k["actor"], k["start"], k["end"], k.get("emotion", ""), k.get("action", "")) for k in sc["talks"]]
    return puppet.PuppetScene(background=bg, actors=actors, talks=talks, duration=sc["duration"], camera=sc["camera"],
                              mood=sc["mood"], env=talk_envelope(sc, fps), fade=sc["fade"])


def talk_envelope(sc: dict, fps: int) -> list[float]:
    """Stand-in loudness (0..1 per frame) until real voices exist: a syllable-like pulse while someone speaks."""
    import math

    n = max(1, int(round(sc["duration"] * fps)))
    env = [0.0] * n
    for k in sc["talks"]:
        for i in range(int(k["start"] * fps), min(n, int(k["end"] * fps))):
            t = i / fps - k["start"]
            env[i] = 0.25 + 0.75 * abs(math.sin(t * math.pi * 4.2))
    return env
