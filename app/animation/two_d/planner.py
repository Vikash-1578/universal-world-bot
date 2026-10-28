"""Storyboard + casting -> a render plan (plain JSON) for the 2D puppet renderer (Milestone 6).

The plan is deterministic: same storyboard + same casting versions -> same plan -> same checksum, so finished scenes
are reused after a restart. Nothing here needs AI.

Timing: until Milestone 8 adds voices, each spoken line gets an estimated time from its word count.
"""
from __future__ import annotations

import io
import re
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw

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
def placeholder_figure(name: str, height: int = 600) -> Image.Image:
    """A plain stand-in 'putla' for a role that has no picture yet (head, body, two legs so the rig still walks)."""
    w = int(height * 0.45)
    im = Image.new("RGBA", (w, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    import hashlib

    hue = hashlib.md5(name.encode("utf-8")).digest()[0] % 8
    col = [(230, 120, 80), (90, 150, 230), (120, 190, 90), (200, 110, 200), (230, 190, 70), (90, 190, 190),
           (240, 150, 170), (150, 120, 220)][hue]
    u = height / 100
    d.ellipse((w / 2 - 13 * u, 2 * u, w / 2 + 13 * u, 28 * u), fill=(245, 215, 180, 255), outline=(60, 40, 30, 255), width=max(1, int(u)))
    d.rectangle((w / 2 - 3 * u, 27 * u, w / 2 + 3 * u, 32 * u), fill=(245, 215, 180, 255))
    d.rounded_rectangle((w / 2 - 17 * u, 31 * u, w / 2 + 17 * u, 64 * u), radius=int(5 * u), fill=col + (255,))
    d.rectangle((w / 2 - 14 * u, 63 * u, w / 2 - 3 * u, 99 * u), fill=(60, 60, 70, 255))
    d.rectangle((w / 2 + 3 * u, 63 * u, w / 2 + 14 * u, 99 * u), fill=(60, 60, 70, 255))
    _label(d, name, w / 2, 47 * u, int(7 * u), int(32 * u))  # role name on the shirt, so the owner knows who is who
    return im


def _label(d: ImageDraw.ImageDraw, text: str, cx: float, cy: float, size: int, max_w: int) -> None:
    from PIL import ImageFont

    font = None
    for cand in ("C:/Windows/Fonts/Nirmala.ttc", "C:/Windows/Fonts/arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(cand, size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    text = text[:10]
    while size > 8 and d.textlength(text, font=font) > max_w and hasattr(font, "font_variant"):
        size -= 2
        font = font.font_variant(size=size)
    d.text((cx, cy), text, fill=(255, 255, 255, 255), font=font, anchor="mm", stroke_width=max(1, size // 10), stroke_fill=(0, 0, 0, 255))


def placeholder_background(mood: str) -> Image.Image:
    im = Image.new("RGB", (1920, 1080), (150, 200, 245))
    d = ImageDraw.Draw(im)
    for y in range(0, 700, 4):
        k = y / 700
        d.rectangle((0, y, 1920, y + 4), fill=(int(120 + 80 * k), int(180 + 50 * k), int(240 + 10 * k)))
    d.rectangle((0, 700, 1920, 1080), fill=(110, 170, 90))
    return im


def load_scene(hub: "Hub", sc: dict, fps: int = 25) -> puppet.PuppetScene:
    data_dir = hub.settings.data_dir

    def img(rel: str) -> Image.Image:
        from app.storage.files import safe_join

        return Image.open(io.BytesIO(safe_join(data_dir, *rel.split("/")).read_bytes()))

    bg = img(sc["background"]["path"]).convert("RGB") if sc["background"].get("path") else placeholder_background(sc["mood"])
    actors = []
    for a in sc["actors"]:
        if a.get("main"):
            sprite = img(a["main"]).convert("RGBA")
            variants = {k: img(v).convert("RGBA") for k, v in (a.get("variants") or {}).items()}
        else:
            sprite, variants = placeholder_figure(a["id"]), {}
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
