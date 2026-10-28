"""Cartoon stories: cast of characters (own look + own voice) -> scenes with dialogue -> narrated video with subtitles."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from app.services import captions as cp
from app.services import cast
from app.services import puppet
from app.services import sfx as sfx_mod
from app.services.image_compose import cover, overlay_title
from app.services.media import VideoError, media_seconds, run_ffmpeg
from app.services.video_pipeline import (
    FORMATS,
    FPS,
    Deps,
    Progress,
    Scene,
    VideoResult,
    _extract_json,
    _noop,
    add_music,
    build_srt,
    caption_geometry,
    concat_clips,
    make_track,
    normalize_audio,
    pick_music,
    render_scene,
    clean_outputs,
)
from app.utils.logging import get_logger

log = get_logger(__name__)

GAP = 0.28  # seconds of silence after each spoken line
MAX_CHARS, MAX_SCENES = 6, 16
NARRATOR = "narrator"


@dataclass
class Character:
    id: str
    name: str
    look: str
    gender: str = "m"
    age: str = "adult"
    size: str = "medium"


@dataclass
class Line:
    speaker: str
    text: str
    emotion: str = ""
    action: str = ""
    sfx: str = ""


@dataclass
class StoryScene:
    setting: str
    who: list[str] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    background: str = ""
    mood: str = "day"
    camera: str = ""
    place: str = ""  # short place name in the story language (shown to the user)


@dataclass
class Story:
    title: str
    description: str
    tags: list[str]
    style: str
    characters: list[Character]
    scenes: list[StoryScene]
    language: str = "hindi"
    fmt: str = "landscape"
    target: int = 90
    voices: dict[str, str] = field(default_factory=dict)  # character id (or "narrator") -> cast preset key
    engine: str = ""  # elevenlabs | gemini | edge (chosen once per story)
    tune: dict[str, tuple[int, int]] = field(default_factory=dict)  # speaker -> (pitch semitones, speed %)
    cast_map: dict[str, str] = field(default_factory=dict)  # character id -> library character id
    eleven_ids: dict[str, str] = field(default_factory=dict)
    sources: list = field(default_factory=list)

    def char(self, cid: str) -> Character | None:
        return next((c for c in self.characters if c.id == cid), None)

    def speakers(self) -> list[str]:
        return [NARRATOR] + [c.id for c in self.characters]


KINDS = {
    "kids": "a short moral story for children with talking animals (clear lesson at the end, gentle humour, nothing scary)",
    "gaon": "a funny or heart-touching Indian village story with everyday people (market, family, neighbours, a twist)",
    "free": "a short story",
}

STORY_PROMPT = (
    "You are a cartoon story writer for YouTube. Write {kind_text} based on: {idea}\n"
    "Language of ALL spoken text: {lang}\n"
    "Return ONLY valid JSON (no markdown) in exactly this shape:\n"
    '{{"title": "...", "description": "...", "tags": ["..."], "style": "...", '
    '"characters": [{{"id": "short_ascii_id", "name": "...", "gender": "m|f", "age": "child|adult|old", "size": "small|medium|big", "look": "..."}}], '
    '"scenes": [{{"place": "...", "setting": "...", "background": "...", "mood": "day", "camera": "zoom_in", "who": ["id"], "lines": [{{"speaker": "narrator or a character id", "text": "...", "emotion": "neutral", "action": "none", "sfx": "none"}}]}}]}}\n'
    "Rules:\n"
    "- {nchar} characters (not counting the narrator), each with a clear personality.\n"
    "- exactly {n} scenes. Each scene has 1-3 spoken lines; most lines are dialogue between characters, the narrator "
    "only sets the scene or moves the story on. Each line is one or two short sentences.\n"
    "- the whole story must be speakable in about {dur} seconds (roughly {words} spoken words in total).\n"
    "- a clear beginning, a problem, a turn and a satisfying ending.\n"
    '- "style": ONE English line, the same 2D cartoon look for every picture (e.g. "bright 2D cartoon, flat colours, soft outlines, '
    'children\'s storybook").\n'
    '- "look": ENGLISH, max 22 words, FIXED appearance of that character (species/age, face, hair, clothes, colours). '
    "It is pasted into every picture so the character looks the same everywhere.\n"
    '- "setting": ENGLISH, max 28 words: place, time of day, what is happening, who is where. '
    "No text, letters, signs or logos in pictures.\n"
    '- "who": ids of the characters visible in that scene (max 3).\n'
    '- "size": small for tiny animals or little kids, big for lions, elephants or tall adults, otherwise medium.\n'
    '- "background": ENGLISH, max 22 words, ONLY the place (no people, no animals), e.g. "village street with mud houses and a big tree".\n'
    '- "place": 2-5 words in the STORY LANGUAGE naming where the scene happens (e.g. "राजू का कमरा", "स्कूल का गेट").\n'
    '- "mood": one of day, sunset, night, indoor, spooky. "camera": one of zoom_in, zoom_out, pan_left, pan_right, static.\n'
    "- title/description/tags in the story language; title max 70 chars; 8-12 tags.\n"
    '- each line: "emotion" one of neutral, happy, sad, angry, scared, surprised; "action" one of none, jump, shake, nod, point, wave, explain (hand gestures: use point/wave/explain often while talking); '
    '"sfx" one of none, footsteps, knock, ding, pop, whoosh, birds, thunder, boing, rain (use sfx rarely, only when it fits).\n'
    "{cast_rule}"
)


SCRIPT_PROMPT = (
    "Below is the user's OWN script for a cartoon video. Turn it into JSON in exactly this shape:\n"
    '{{"title": "...", "description": "...", "tags": ["..."], "style": "...", '
    '"characters": [{{"id": "short_ascii_id", "name": "...", "gender": "m|f", "age": "child|adult|old", "size": "small|medium|big", "look": "..."}}], '
    '"scenes": [{{"place": "...", "setting": "...", "background": "...", "mood": "day", "camera": "zoom_in", "who": ["id"], '
    '"lines": [{{"speaker": "narrator or a character id", "text": "...", "emotion": "neutral", "action": "none", "sfx": "none"}}]}}]}}\n'
    "Rules:\n"
    "- KEEP EVERY SPOKEN LINE EXACTLY AS WRITTEN (same words, same language, same order). Do not add or remove dialogue.\n"
    "- \"Name: text\" is that character's dialogue; any other sentence is the narrator.\n"
    "- start a new scene when the place or time changes, or every 2-4 lines.\n"
    "- name = the character's name exactly as in the script; look = ENGLISH, max 22 words, fixed appearance.\n"
    "- place = 2-5 words in the script's language; setting and background in ENGLISH (background = only the place, no people).\n"
    "- mood one of day, sunset, night, indoor, spooky; camera one of zoom_in, zoom_out, pan_left, pan_right, static.\n"
    "- emotion one of neutral, happy, sad, angry, scared, surprised; action one of none, jump, shake, nod, point, wave, explain; "
    "sfx one of none, footsteps, knock, ding, pop, whoosh, birds, thunder, boing, rain.\n"
    "- style: ONE English line for the cartoon look. title/description/tags in the script's language.\n\n"
    "SCRIPT:\n{script}"
)


def scene_count(duration: int) -> int:
    return max(4, min(MAX_SCENES, round(duration / 8)))


def build_story_prompt(idea: str, language: str, kind: str, duration: int, cast_hint: str = "") -> str:
    n = scene_count(duration)
    lang = "Hindi in Devanagari script (natural spoken Hindi)" if language == "hindi" else "simple, clear, friendly English"
    return STORY_PROMPT.format(
        kind_text=KINDS.get(kind, KINDS["free"]), idea=idea.strip()[:400], lang=lang, n=n, dur=duration,
        nchar="2-4" if duration <= 120 else "3-5", words=int(duration * (1.7 if language == "hindi" else 2.0)),
        cast_rule=("- MUST use these existing characters with exactly these names and looks: " + cast_hint + "\n") if cast_hint else "",
    )


def story_to_dict(st: Story) -> dict:
    return {
        "title": st.title, "description": st.description, "tags": st.tags, "style": st.style,
        "characters": [{"id": c.id, "name": c.name, "gender": c.gender, "age": c.age, "size": c.size, "look": c.look} for c in st.characters],
        "scenes": [{"place": s.place, "setting": s.setting, "background": s.background, "mood": s.mood, "camera": s.camera, "who": s.who, "lines": [{"speaker": l.speaker, "text": l.text, "emotion": l.emotion, "action": l.action, "sfx": l.sfx} for l in s.lines]} for s in st.scenes],
    }


def story_state(st: Story) -> dict:
    """Everything to rebuild the story later (projects / other formats / next episode)."""
    return {"story": story_to_dict(st), "language": st.language, "fmt": st.fmt, "target": st.target, "voices": dict(st.voices),
            "tune": {k: list(v) for k, v in st.tune.items()}, "engine": st.engine, "eleven_ids": dict(st.eleven_ids),
            "cast_map": dict(st.cast_map)}


def story_from_state(d: dict, fmt: str | None = None) -> Story:
    st = parse_story(json.dumps(d["story"], ensure_ascii=False), d.get("language", "hindi"), fmt or d.get("fmt", "landscape"),
                     int(d.get("target", 90)))
    st.voices.update(d.get("voices") or {})
    st.tune = {k: (int(v[0]), int(v[1])) for k, v in (d.get("tune") or {}).items()}
    st.engine = d.get("engine", "")
    st.eleven_ids = dict(d.get("eleven_ids") or {})
    st.cast_map = dict(d.get("cast_map") or {})
    return st


def build_edit_prompt(st: Story, instruction: str, duration: int) -> str:
    return (
        "Here is a cartoon story as JSON. Change it as the user asks and return the COMPLETE updated JSON in exactly the same "
        "shape (same rules: fixed English 'look' per character, 'setting' per scene, speakers are narrator or a character id, "
        f"about {scene_count(duration)} scenes unless asked otherwise). Keep the language of the spoken text.\n"
        f"USER REQUEST: {instruction.strip()[:400]}\n\nSTORY JSON:\n" + json.dumps(story_to_dict(st), ensure_ascii=False)
    )


def _slug(s: str, i: int) -> str:
    t = re.sub(r"[^a-z0-9_]+", "_", (s or "").lower()).strip("_")
    return t[:20] or f"c{i + 1}"


def parse_story(text: str, language: str = "hindi", fmt: str = "landscape", target: int = 90) -> Story:
    d = _extract_json(text)
    chars: list[Character] = []
    for i, c in enumerate(d.get("characters") or []):
        if not isinstance(c, dict) or not str(c.get("name") or "").strip():
            continue
        cid = _slug(str(c.get("id") or c.get("name")), i)
        if any(x.id == cid for x in chars):
            cid = f"{cid}{i}"
        chars.append(Character(
            cid, str(c["name"]).strip()[:30], str(c.get("look") or c["name"]).strip()[:200],
            "f" if str(c.get("gender", "m")).lower().startswith("f") else "m",
            str(c.get("age", "adult")).lower() if str(c.get("age", "")).lower() in ("child", "adult", "old") else "adult",
            str(c.get("size", "medium")).lower() if str(c.get("size", "")).lower() in ("small", "medium", "big") else "medium",
        ))
    chars = chars[:MAX_CHARS]
    ids = {c.id for c in chars}
    scenes: list[StoryScene] = []
    for s in d.get("scenes") or []:
        if not isinstance(s, dict):
            continue
        lines = []
        for l in s.get("lines") or []:
            if not isinstance(l, dict):
                continue
            t = " ".join(str(l.get("text") or "").split())
            if not t:
                continue
            sp = str(l.get("speaker") or NARRATOR).strip()
            sp = sp if sp in ids else (_slug(sp, 0) if _slug(sp, 0) in ids else NARRATOR)
            emo = str(l.get("emotion") or "").lower()
            act = str(l.get("action") or "").lower()
            fx = str(l.get("sfx") or "").lower()
            lines.append(Line(sp, t[:400], emo if emo in puppet.EMOTIONS else "", act if act in puppet.ACTIONS else "",
                              fx if fx in sfx_mod.NAMES else ""))
        if not lines:
            continue
        who = [w for w in (s.get("who") or []) if w in ids][:3]
        if not who:
            who = [l.speaker for l in lines if l.speaker in ids][:3]
            who = list(dict.fromkeys(who))
        mood = str(s.get("mood") or "day").lower()
        cam = str(s.get("camera") or "").lower()
        scenes.append(StoryScene(" ".join(str(s.get("setting") or "").split())[:300], who, lines,
                                 " ".join(str(s.get("background") or "").split())[:240],
                                 mood if mood in puppet.MOODS else "day", cam if cam in puppet.CAMERAS else "",
                                 " ".join(str(s.get("place") or "").split())[:60]))
    scenes = scenes[:MAX_SCENES]
    if not scenes:
        raise VideoError("Kahani ka format sahi nahi aaya, dobara try karo.")
    tags = [str(t).strip().lstrip("#") for t in (d.get("tags") or []) if str(t).strip()][:14]
    st = Story(
        str(d.get("title") or "Kahani")[:90], str(d.get("description") or "")[:600], tags,
        str(d.get("style") or "bright 2D cartoon, flat colours, soft outlines, storybook")[:200], chars, scenes,
        language, fmt, target,
    )
    for c in st.characters:
        st.voices[c.id] = cast.pick(language, c.gender, c.age, f"{c.name} {c.look}").key
    st.voices[NARRATOR] = cast.pick(language, "m", "narrator").key
    return st


async def make_story(idea: str, deps: Deps, *, language: str = "hindi", kind: str = "free", fmt: str = "landscape",
                     duration: int = 90, previous: Story | None = None, instruction: str | None = None,
                     progress: Progress = _noop, cast_names: list[str] | None = None, script: str | None = None) -> Story:
    duration = max(30, min(180, int(duration)))
    if previous is not None and instruction:
        await progress("✏️ Kahani badal raha hoon...")
        prompt = build_edit_prompt(previous, instruction, duration)
    elif script:
        await progress("📜 Script padh ke characters dhoondh raha hoon...")
        prompt = SCRIPT_PROMPT.format(script=script.strip()[:6000])
        duration = max(duration, 30)
    else:
        await progress("📖 Kahani aur characters bana raha hoon...")
        hint = "; ".join(f"{m['name']} ({m.get('look', '')[:120]})" for m in (find_character(n) for n in (cast_names or [])) if m)
        prompt = build_story_prompt(idea, language, kind, duration, hint)
    st = None
    for i in range(3):
        try:
            extra = "" if i == 0 else "\nIMPORTANT: output ONLY the complete JSON object, nothing else."
            st = parse_story(await deps.llm(prompt + extra), language, fmt, duration)
            break
        except VideoError as e:
            log.warning("story_json_bad try=%s err=%s", i + 1, e)
            if i == 2:
                raise VideoError("AI ne kahani ka JSON nahi diya (3 baar try kiya). Thodi der baad dobara try karo.") from e
            await progress(f"📖 Kahani dobara likhwa raha hoon ({i + 2}/3)...")
    if previous is not None:  # keep the voices the user already picked
        for k, v in previous.voices.items():
            if k in st.voices:
                st.voices[k] = v
        st.engine = previous.engine
    return st


# ---------------------------------------------------------------- pictures
def scene_prompt(st: Story, sc: StoryScene, limit: int = 480) -> str:
    chars = [c for c in (st.char(w) for w in sc.who) if c]

    def build(look_words: int, setting_chars: int) -> str:
        looks = "; ".join(f"{c.name}: {' '.join(c.look.split()[:look_words])}" for c in chars)
        parts = [st.style, sc.setting[:setting_chars]]
        if looks:
            parts.append("Characters: " + looks)
        return ". ".join(p for p in parts if p)

    for lw, sch in ((22, 260), (16, 200), (11, 160), (8, 120)):
        p = build(lw, sch)
        if len(p) <= limit:
            return p
    return build(6, 100)[:limit]


# ---------------------------------------------------------------- voices
async def join_lines(files: list[Path], out: Path, gap: float = GAP) -> Path:
    inputs: list[str] = []
    for f in files:
        inputs += ["-i", str(f)]
    parts = [f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,apad=pad_dur={gap}[a{i}]" for i in range(len(files))]
    cat = "".join(f"[a{i}]" for i in range(len(files))) + f"concat=n={len(files)}:v=0:a=1[a]"
    await run_ffmpeg(inputs + ["-filter_complex", ";".join(parts + [cat]), "-map", "[a]", "-c:a", "pcm_s16le", str(out)], timeout=300)
    return out


async def speak_scene(st: Story, sc: StoryScene, idx: int, deps: Deps, workdir: Path, footsteps: bool = False):
    """-> (scene wav, seconds, caption words, [Talk-like tuples (speaker, start, end, emotion, action)])"""
    files: list[Path] = []
    secs: list[float] = []
    for j, ln in enumerate(sc.lines):
        key = st.voices.get(ln.speaker) or st.voices.get(NARRATOR) or ""
        data, ext = await cast.say(deps.voices, ln.text, key, st.language, ln.emotion, st.engine or "edge",
                                   st.eleven_ids.get(ln.speaker))
        semis, speed = st.tune.get(ln.speaker, (0, 0))
        if semis or speed:
            try:
                data, ext = await cast.tune(data, ext, semis, speed)
            except VideoError as e:
                log.warning("tune_failed err=%s", e)
        p = workdir / f"s{idx}_{j}.{ext}"
        p.write_bytes(data)
        files.append(p)
        secs.append(await media_seconds(p))
    out = await join_lines(files, workdir / f"scene_audio_{idx}.wav")
    words: list[cp.Word] = []
    talks: list[tuple[str, float, float, str, str]] = []
    events: list[tuple[str, float]] = [("footsteps", 0.0)] if footsteps else []
    off = 0.0
    for ln, s in zip(sc.lines, secs):
        words += cp.estimate_words(ln.text, s, off)
        talks.append((ln.speaker, off, off + s, ln.emotion, ln.action))
        if ln.sfx:
            events.append((ln.sfx, off))
        off += s + GAP
    if events:
        try:
            out = await sfx_mod.mix_sfx(out, events, workdir, str(idx))
        except VideoError as e:
            log.warning("sfx_mix_failed err=%s", e)
    return out, await media_seconds(out), words, talks


def distinct_voices(st: Story) -> None:
    """Every speaker gets its own sound: library default voice first, then pitch shifts for any repeats."""
    from app.services import library

    for c in st.characters:
        e = library.entry(st.cast_map.get(c.id, ""))
        if e and e.get("voice") and (st.language == "hindi") == e["voice"].startswith("hi-"):
            st.voices[c.id] = e["voice"]
    seen: dict[tuple, int] = {}
    shifts = [0, 3, -3, 5, -5, 7]
    for sid in st.speakers():
        semis, speed = st.tune.get(sid, (0, 0))
        k = (st.voices.get(sid), semis, speed)
        n = seen.get(k, 0)
        seen[k] = n + 1
        if n:
            st.tune[sid] = (max(-8, min(8, semis + shifts[n % len(shifts)])), speed)


async def prepare_voices(st: Story, voices) -> str:
    """Choose the voice engine once per story; with ElevenLabs give every speaker its own voice."""
    if not st.engine:
        st.engine = await cast.pick_engine(voices, st.language)
    if st.engine == "elevenlabs" and not st.eleven_ids:
        try:
            vs = await voices.eleven_voices()
        except Exception:  # noqa: BLE001
            vs = []
        used: set[str] = set()
        for sid in st.speakers():
            vid = cast.eleven_choose(vs, cast.get(st.voices.get(sid), st.language), used)
            if vid:
                st.eleven_ids[sid] = vid
                used.add(vid)
    return st.engine


# ---------------------------------------------------------------- characters (puppet mode)
SPRITE_PROMPT = (
    "{style}. Full body picture of ONE cartoon character: {name}, {look}. Standing in a three-quarter view, body and face "
    "turned slightly to the right, the whole body from head to feet visible and centered, on a plain flat solid bright "
    "green background, no shadow, no ground, nothing else in the picture, no text. The character itself has no green colour."
)
BG_PROMPT = "{style}. {place}. Empty background scene with no people, no animals and no characters, wide shot, open ground in the lower part. No text."
KEEP = "Keep exactly the same character, same drawing style, same clothes, same pose and the same plain bright green background. Only change: "
VARIANTS = {
    "talk": "the mouth is wide open as if speaking.",
    "blink": "the eyes are closed (blinking).",
    "happy": "a big happy smile.",
    "sad": "a sad face with a downturned mouth and sad eyes.",
    "angry": "an angry face with frowning eyebrows.",
    "scared": "a scared face with wide eyes and a small open mouth.",
    "surprised": "a surprised face with a round open mouth and raised eyebrows.",
    "explain": "both hands are raised open in front of the chest, as if explaining something; the face and head stay exactly the same.",
    "point": "one arm is stretched out pointing forward with the index finger; the face and head stay exactly the same.",
    "wave": "one hand is raised high, waving hello; the face and head stay exactly the same.",
}


def character_dir() -> Path:
    return Path(os.environ.get("CHARACTER_DIR") or "data/characters")


def character_key(c: Character, style: str) -> str:
    return f"{_slug(c.id, 0)}_{hashlib.md5((c.look + '|' + style).encode('utf-8')).hexdigest()[:8]}"


def _meta(p: Path) -> dict:
    try:
        return json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _base_files(d: Path) -> list[Path]:
    return [p for p in d.glob("*.png") if "__" not in p.stem]


def list_characters(limit: int = 30) -> list[tuple[str, Path]]:
    d = character_dir()
    files = sorted(_base_files(d), key=lambda x: x.stat().st_mtime, reverse=True)[:limit] if d.exists() else []
    return [(_meta(p).get("name") or p.stem, p) for p in files]


def find_character(name: str) -> dict | None:
    """Saved character by name (case-insensitive) -> its meta with 'path'."""
    n = (name or "").strip().casefold()
    d = character_dir()
    if not n or not d.exists():
        return None
    for p in sorted(_base_files(d), key=lambda x: x.stat().st_mtime, reverse=True):
        m = _meta(p)
        nm = str(m.get("name", "")).strip().casefold()
        if nm == n or (nm.split() and nm.split()[0] == n):
            m["path"] = str(p)
            return m
    return None


def load_variants(base_path: Path) -> dict[str, Image.Image]:
    """Saved full-canvas variants (same canvas as the raw base picture)."""
    out: dict[str, Image.Image] = {}
    for p in base_path.parent.glob(base_path.stem + "__f_*.png"):
        k = p.stem.split("__f_", 1)[1]
        if k in VARIANTS:
            try:
                out[k] = Image.open(p).convert("RGBA")
            except Exception:  # noqa: BLE001
                pass
    return out


def _fit_canvas(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale to the same height, then centre-pad/crop the width (edit models may change the aspect)."""
    w, h = size
    if img.size == size:
        return img
    s = h / img.height
    im = img.resize((max(1, int(img.width * s)), h), Image.LANCZOS)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(im, ((w - im.width) // 2, 0), im)
    return out


def save_character(key: str, img: Image.Image, raw: bytes | None, meta: dict) -> Path:
    d = character_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{key}.png"
    img.save(path, "PNG")
    if raw:
        (d / f"{key}__raw.img").write_bytes(raw)
    path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return path


async def make_sprite(c: Character, st: Story, deps: Deps, seed: int, style: str | None = None, force: bool = False):
    """-> (base sprite, raw green picture or None, saved path or None). Reuses saved characters (unless force)."""
    lib_id = st.cast_map.get(c.id)
    if lib_id:
        from app.services import library

        return await library.ensure(lib_id, deps, seed, force=force)
    d = character_dir()
    path = d / f"{character_key(c, st.style)}.png"
    if force:
        for p in d.glob(path.stem + "*"):
            try:
                p.unlink()
            except OSError:
                pass
    elif not path.exists():
        m = find_character(c.name)
        if m:
            path = Path(m["path"])
    if path.exists() and not force:
        try:
            raw_p = path.parent / f"{path.stem}__raw.img"
            return Image.open(path).convert("RGBA"), (raw_p.read_bytes() if raw_p.exists() else None), path
        except Exception:  # noqa: BLE001
            pass
    path = d / f"{character_key(c, st.style)}.png"
    prompt = SPRITE_PROMPT.format(style=st.style, name=c.name, look=c.look)[:500]
    for k in range(3):
        try:
            data = await deps.images.generate(prompt, seed=seed + 101 * k, size="portrait", style=style, enhance=False, no_text=True)
        except Exception as e:  # noqa: BLE001
            log.warning("sprite_gen_failed char=%s err=%s", c.id, type(e).__name__)
            await asyncio.sleep(1.5)
            continue
        if deps.usage is not None:
            deps.usage.add("images")
        img = await asyncio.to_thread(puppet.key_sprite, data)
        if img is not None:
            try:
                save_character(path.stem, img, data, {"name": c.name, "look": c.look, "style": st.style, "voice": st.voices.get(c.id)})
            except OSError as e:
                log.warning("sprite_save_failed err=%s", e)
                return img, data, None
            return img, data, path
    return None, None, None


class EditBudget:
    """Stop asking for edits after the edit API fails twice (no credit / no model)."""

    def __init__(self) -> None:
        self.fails = 0

    @property
    def ok(self) -> bool:
        return self.fails < 2


async def make_variants(base: Image.Image, raw: bytes | None, path: Path | None, needed: list[str], deps: Deps,
                        budget: EditBudget, seed: int) -> tuple[Image.Image, dict[str, Image.Image]]:
    """-> (base, variants) cropped to ONE common box, so mouth / arms / legs line up when frames are swapped."""
    if raw is None:
        return base, {}
    base_full = await asyncio.to_thread(puppet.key_sprite, raw, 900, 70, False)
    if base_full is None:
        return base, {}
    bb = base_full.getchannel("A").getbbox()
    have = {k: _fit_canvas(v, base_full.size) for k, v in (load_variants(path) if path is not None else {}).items()}
    edit = getattr(deps.images, "edit", None)
    for k in needed:
        if k in have or k not in VARIANTS or edit is None or not budget.ok:
            continue
        try:
            data = await edit(raw, KEEP + VARIANTS[k], "image/jpeg" if raw[:3] == b"\xff\xd8\xff" else "image/png",
                              seed=seed, translate=False)
        except Exception as e:  # noqa: BLE001
            budget.fails += 1
            log.warning("variant_edit_failed kind=%s err=%s %s", k, type(e).__name__, str(e)[:100])
            continue
        if deps.usage is not None:
            deps.usage.add("images")
        img = await asyncio.to_thread(puppet.key_sprite, data, 900, 70, False)
        if img is None:
            continue
        img = _fit_canvas(img, base_full.size)
        vb = img.getchannel("A").getbbox()
        if not vb or abs(vb[3] - bb[3]) > 0.06 * base_full.height or abs((vb[3] - vb[1]) - (bb[3] - bb[1])) > 0.2 * (bb[3] - bb[1]):
            log.info("variant_rejected kind=%s (pose moved too much)", k)
            continue
        have[k] = img
        if path is not None:
            try:
                img.save(path.parent / f"{path.stem}__f_{k}.png", "PNG")
            except OSError:
                pass
    if not have:
        return base, {}
    x0, y0, x1, y1 = bb
    for v in have.values():
        b2 = v.getchannel("A").getbbox()
        if b2:
            x0, y0, x1, y1 = min(x0, b2[0]), min(y0, b2[1]), max(x1, b2[2]), max(y1, b2[3])
    box = (x0, y0, x1, y1)
    return base_full.crop(box), {k: v.crop(box) for k, v in have.items()}


def variants_needed(st: Story, cid: str) -> list[str]:
    speaks = any(ln.speaker == cid for sc in st.scenes for ln in sc.lines)
    need = ["talk", "blink"] + (["explain"] if speaks else [])
    for sc in st.scenes:
        for ln in sc.lines:
            if ln.speaker != cid:
                continue
            for k in (ln.emotion, ln.action):
                if k and k in VARIANTS and k not in need:
                    need.append(k)
    return need


def plain_background(w: int, h: int, mood: str = "day") -> Image.Image:
    """Sky + ground gradient, used when the background picture could not be made."""
    from PIL import ImageDraw

    sky = {"night": ((20, 30, 70), (60, 70, 120)), "sunset": ((250, 150, 90), (255, 210, 150)),
           "indoor": ((235, 215, 185), (250, 235, 210)), "spooky": ((40, 50, 60), (80, 90, 100))}.get(mood, ((110, 180, 240), (200, 230, 255)))
    ground = (95, 170, 80) if mood not in ("indoor", "spooky") else (170, 130, 95)
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    gy = int(h * 0.68)
    for y in range(gy):
        t = y / max(1, gy - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(*sky)))
    d.rectangle((0, gy, w, h), fill=ground)
    return img


# ---------------------------------------------------------------- render
async def render_story(
    st: Story, deps: Deps, *, style: str | None = None, music: bool = False, captions: str = "word",
    progress: Progress = _noop, animate: bool = True, expressions: bool = True, library_bg: bool = True,
) -> VideoResult:
    fmt = st.fmt if st.fmt in FORMATS else "landscape"
    w, h, size_name = FORMATS[fmt]
    deps.out_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="uwstory_"))
    n = len(st.scenes)
    t0 = time.time()
    if deps.images is None or not getattr(deps.images, "enabled", True):
        raise VideoError("Image key set nahi hai, kahani ki pictures nahi ban sakti.")
    try:
        seed = random.randint(1, 2_000_000)
        try:
            await prepare_voices(st, deps.voices)
        except Exception as e:  # noqa: BLE001
            log.warning("prepare_voices_failed err=%s", e)
            st.engine = "edge"
        sprites: dict[str, Image.Image] = {}
        variants: dict[str, dict[str, Image.Image]] = {}
        if animate and st.characters:
            await progress(f"🎭 Characters bana raha hoon (0/{len(st.characters)})...")
            budget = EditBudget()
            for i, c in enumerate(st.characters):
                img, raw, path = await make_sprite(c, st, deps, seed + i, style)
                if img is None:
                    log.warning("sprite_failed char=%s -> picture mode", c.id)
                    await progress(f"⚠ {c.name} ka cut-out nahi bana, normal picture mode me bana raha hoon...")
                    sprites, variants = {}, {}
                    animate = False
                    break
                sprites[c.id] = img
                if expressions:
                    await progress(f"😀 {c.name} ke expressions bana raha hoon...")
                    sprites[c.id], variants[c.id] = await make_variants(img, raw, path, variants_needed(st, c.id), deps, budget, seed + i)
                await progress(f"🎭 Characters bana raha hoon ({i + 1}/{len(st.characters)})...")
        scenes = [Scene(" ".join(l.text for l in s.lines),
                        BG_PROMPT.format(style=st.style, place=(s.background or s.setting))[:500] if animate else scene_prompt(st, s))
                  for s in st.scenes]
        talks: list[list[tuple[str, float, float, str, str]]] = [[] for _ in range(n)]
        enters: list[bool] = []
        seen: list[str] = []
        for ss in st.scenes:
            who = [c for c in ss.who if c in sprites]
            enters.append(animate and any(c not in seen for c in who))
            seen = who
        done = {"v": 0, "i": 0}

        async def report() -> None:
            await progress(f"🎙 Awaaz {done['v']}/{n}  ·  🖼 {'Backgrounds' if animate else 'Images'} {done['i']}/{n}")

        async def do_voice(i: int) -> None:
            p, sec, words, tk = await speak_scene(st, st.scenes[i], i, deps, workdir, enters[i] if animate else False)
            scenes[i].audio_path, scenes[i].audio_sec, scenes[i].words = p, sec, words
            talks[i] = tk
            done["v"] += 1
            await report()

        img_sem = asyncio.Semaphore(3)

        img_errors: list[str] = []

        async def do_image(i: int) -> None:
            async with img_sem:
                last: Exception | None = None
                if animate and library_bg:
                    from app.services import library

                    ss_ = st.scenes[i]
                    pid = library.best_place(f"{ss_.background} {ss_.setting} {ss_.place}")
                    lp = await library.ensure_place(pid, deps, size_name) if pid else None
                    if lp is not None:
                        scenes[i].image_path = lp
                        done["i"] += 1
                        await report()
                        return
                for k in range(4):
                    try:
                        data = await deps.images.generate(scenes[i].image_prompt, seed=seed, size=size_name,
                                                          style=style, enhance=False, no_text=True)
                        p = workdir / f"img_{i}.jpg"
                        p.write_bytes(data)
                        scenes[i].image_path = p
                        if deps.usage is not None:
                            deps.usage.add("images")
                        break
                    except Exception as e:  # noqa: BLE001
                        last = e
                        if getattr(e, "status", None) in (401, 402, 403):  # no credit / bad key: retrying will not help
                            break
                        await asyncio.sleep(3 * (k + 1))  # 429 / busy server: wait longer each time
                if scenes[i].image_path is None:
                    img_errors.append(f"{type(last).__name__}: {str(last)[:80]}")
                    log.warning("story_image_failed scene=%s err=%s", i, last)
                done["i"] += 1
                await report()

        await report()
        res = await asyncio.gather(*[do_voice(i) for i in range(n)], *[do_image(i) for i in range(n)], return_exceptions=True)
        for r in res:
            if isinstance(r, BaseException):
                raise VideoError(f"awaaz ya image nahi bani: {type(r).__name__}: {str(r)[:120]}")
        prev: Path | None = None
        for sc in scenes:
            if sc.image_path is None:
                sc.image_path = prev
            prev = sc.image_path or prev
        for sc in reversed(scenes):
            if sc.image_path is None:
                sc.image_path = prev
            prev = sc.image_path or prev
        if any(sc.image_path is None for sc in scenes):
            if not animate:
                raise VideoError("images nahi ban paayi (Pollinations credit / Cloudflare CF_ACCOUNT_ID+CF_API_TOKEN dekho): " + (img_errors[0] if img_errors else ""))
            # characters are ready -> still make the video on simple painted backgrounds
            await progress("⚠ Background images nahi bani (" + (img_errors[0] if img_errors else "?") + "), simple background laga raha hoon...")
            for i, sc in enumerate(scenes):
                p = workdir / f"plain_{i}.jpg"
                plain_background(w, h, st.scenes[i].mood).save(p, "JPEG", quality=90)
                sc.image_path = p

        clips: list[Path] = []
        thumb_frame: Image.Image | None = None
        _, _, cap_y = caption_geometry(w, h)
        prev_who: list[str] = []
        for i, sc in enumerate(scenes):
            await progress(f"🎞 {'Animation' if animate else 'Video'} bana raha hoon {i + 1}/{n} (thoda time lagega)...")
            track = await asyncio.to_thread(make_track, sc.words, sc.duration, w, h, workdir, f"cap{i}", captions)
            if not animate:
                clips.append(await render_scene(i, sc, track, w, h, workdir))
                continue
            ss = st.scenes[i]
            who = [c for c in ss.who if c in sprites]
            xs = puppet.layout(len(who))
            actors = [puppet.Actor(cid, sprites[cid], st.char(cid).size if st.char(cid) else "medium", x,
                                   None if cid in prev_who else ("left" if x < 0.5 else "right"),
                                   variants.get(cid, {}), flip=x > 0.5)
                      for cid, x in zip(who, xs)]
            prev_who = who
            with Image.open(sc.image_path) as bgi:
                bg = bgi.convert("RGB")
            ps = puppet.PuppetScene(
                bg, actors, [puppet.Talk(a, s0, s1, emo, act) for a, s0, s1, emo, act in talks[i] if a != NARRATOR], sc.duration,
                ss.camera or puppet.CAMERAS[i % len(puppet.CAMERAS)], ss.mood,
                await asyncio.to_thread(puppet.envelope, sc.audio_path, FPS),
            )
            if thumb_frame is None:
                thumb_frame = await asyncio.to_thread(puppet.preview, ps, 1280, 720, min(sc.duration * 0.8, 2.5))
            out = workdir / f"scene_{i}.mp4"
            await asyncio.to_thread(puppet.render_puppet, ps, w, h, FPS, out, sc.audio_path, track, cap_y)
            clips.append(out)
        final = deps.out_dir / f"story_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        await progress("🔗 Jod raha hoon...")
        await concat_clips(clips, final, workdir)
        total = sum(s.duration for s in scenes)
        if music:
            m = None
            if deps.music is not None:
                m = await deps.music.get(st.style or st.title, total, workdir)
            m = m or pick_music()
            if m:
                try:
                    mixed = workdir / "mixed.mp4"
                    await add_music(final, m, mixed, 0.08)
                    shutil.move(str(mixed), final)
                except VideoError as e:
                    log.warning("story_music_failed err=%s", e)
        try:
            await normalize_audio(final, workdir)
        except VideoError as e:
            log.warning("loudnorm_failed err=%s", e)
        srt = final.with_suffix(".srt")
        srt.write_text(build_srt(scenes, 5 if fmt == "shorts" else 8), encoding="utf-8")
        thumb = None
        try:
            import io as _io

            buf = _io.BytesIO()
            if thumb_frame is not None:
                thumb_frame.convert("RGB").save(buf, "JPEG", quality=92)
            else:
                with Image.open(scenes[0].image_path) as im:
                    cover(im, 1280, 720).save(buf, "JPEG", quality=92)
            thumb = await asyncio.to_thread(overlay_title, buf.getvalue(), st.title, None, "thumb")
        except Exception as e:  # noqa: BLE001
            log.warning("thumb_failed err=%s", type(e).__name__)
        qc = None
        try:
            from app.services.qc import quality_check

            await progress("🔎 Quality check...")
            qc = await quality_check(final, (w, h), total, srt)
        except Exception as e:  # noqa: BLE001
            log.warning("qc_failed err=%s", e)
        clean_outputs(deps.out_dir)
        if deps.usage is not None:
            deps.usage.add("videos")
        log.info("story_done scenes=%s sec=%.0f animate=%s took=%.0fs", n, total, animate, time.time() - t0)
        return VideoResult(final, srt, st, total, thumb, final.stat().st_size / 1e6, qc, [])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
