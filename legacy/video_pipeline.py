"""Video production pipeline: topic -> (research) -> script -> voice + pictures/stock footage -> captions -> mp4.

Two halves so a human can approve in between:
    make_plan()   research + script   (cheap)
    render_plan() voice, visuals, render, QC (slow)
produce_video() runs both.

Everything runs on ffmpeg (static binary from the imageio-ffmpeg wheel) and Pillow. Captions are drawn
as PNGs (word-by-word highlight) and overlaid as ONE ffconcat track, so ffmpeg needs no libass/freetype.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from PIL import Image

from app.services import captions as cp
from app.services.captions import Word
from app.services.image_compose import cover, overlay_title
from app.services.media import (  # noqa: F401  (re-exported: other modules import them from here)
    VideoError,
    ffmpeg_available,
    ffmpeg_exe,
    media_seconds,
    run_ffmpeg,
)
from app.services.music import pick_folder_music
from app.utils.logging import get_logger

log = get_logger(__name__)

FPS = 25
HOLD = 0.35  # seconds of calm after each narration line
FORMATS = {"shorts": (720, 1280, "portrait"), "landscape": (1280, 720, "landscape"), "square": (1080, 1080, "square")}
MIN_DURATION, MAX_DURATION = 15, 180
Progress = Callable[[str], Awaitable[None]]


@dataclass
class Scene:
    narration: str
    image_prompt: str
    audio_path: Path | None = None
    image_path: Path | None = None
    audio_sec: float = 0.0
    stock_query: str = ""
    stock_path: Path | None = None  # a stock VIDEO file (image stock goes to image_path)
    stock_credit: str = ""
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.audio_sec + HOLD


@dataclass
class Plan:
    title: str
    description: str
    tags: list[str]
    visual_style: str
    scenes: list[Scene]
    language: str = "hindi"
    fmt: str = "shorts"
    sources: list[tuple[str, str]] = field(default_factory=list)
    facts: str = ""
    target: int = 0  # requested length in seconds


@dataclass
class VideoResult:
    path: Path
    srt_path: Path
    plan: Plan
    seconds: float
    thumb: bytes | None = None
    size_mb: float = 0.0
    qc: object | None = None
    credits: list[str] = field(default_factory=list)


@dataclass
class Deps:
    llm: Callable[[str], Awaitable[str]]
    voices: object  # VoiceService
    images: object  # ImageGenerator (generate) or None
    out_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "uw_videos")
    vision: Callable[..., Awaitable[str]] | None = None  # (prompt, [jpeg bytes]) -> text
    stock: object | None = None  # StockService
    music: object | None = None  # MusicService
    research: object | None = None  # Researcher
    usage: object | None = None  # UsageTracker


async def _noop(_: str) -> None:
    return None


# ---------------------------------------------------------------- planning
LANG_INSTR = {
    "hindi": "Hindi written in Devanagari script (natural spoken Hindi; English words only where unavoidable)",
    "english": "simple, clear, friendly English",
}
PLAN_PROMPT = (
    "You are a YouTube script writer. Write a {dur}-second {kind} about: {topic}\n"
    "Narration language: {lang}\n"
    "{facts}"
    "Return ONLY valid JSON (no markdown, no comments) in exactly this shape:\n"
    '{{"title": "...", "description": "...", "tags": ["..."], "visual_style": "...", '
    '"scenes": [{scene_shape}]}}\n'
    "Rules:\n"
    "- exactly {n} scenes. Each narration is 1-2 short spoken sentences (about {words} words), engaging and natural. "
    "Scene 1 is a strong hook. The last scene ends with a short call to action (like / subscribe).\n"
    "- the whole narration must be speakable in about {dur} seconds in total; never longer.\n"
    "- Match the mood of the topic: a cute or happy topic gets a warm, cute, positive script (no scary or sad angle).\n"
    "- the LAST scene's image must be a warm closing moment with the same main character; never a phone, screen, "
    "app, button or any text/icons. The like/subscribe line is only spoken, never drawn.\n"
    "- title: catchy, max 70 characters, in the narration language.\n"
    "- description: 2-3 lines plus a few hashtags, in the narration language.\n"
    "- tags: 8-12 short tags.\n"
    "- visual_style: ONE English line describing the consistent look and the main character, "
    '(for example "cute 3D cartoon, bright colors, a small orange lion cub with a red scarf").\n'
    '- each "image": a detailed ENGLISH picture description for that scene (subject, setting, action, lighting). '
    "No text, letters, signs or logos inside pictures.\n"
    "{stock_rule}"
)
FACTS_RULE = (
    "VERIFIED FACTS (use these for every claim; do not invent numbers, dates or names that are not here "
    "or that you are not sure of). Use only facts that fit the topic and its mood; ignore any that are off-topic, "
    "scary or sad when the topic is cute or happy:\n{facts}\n"
)
STOCK_RULE = (
    '- each "stock": 2-4 ENGLISH keywords to search free stock VIDEO footage for that scene '
    '(concrete and filmable, e.g. "lion walking savanna", never abstract words).\n'
)


def scene_count(duration: int) -> int:
    return max(3, min(12, round(duration / 7)))


def build_plan_prompt(topic: str, language: str, fmt: str, duration: int, facts: str = "", stock: bool = False) -> str:
    n = scene_count(duration)
    shape = '{{"narration": "...", "image": "..."' + (', "stock": "..."' if stock else "") + "}}"
    return PLAN_PROMPT.format(
        dur=duration,
        kind="vertical YouTube Short" if fmt == "shorts" else "YouTube video",
        topic=topic.strip()[:400],
        lang=LANG_INSTR.get(language, LANG_INSTR["english"]),
        n=n,
        words=max(7, min(22, int(duration / n * (1.7 if language == "hindi" else 2.1)))),
        facts=FACTS_RULE.format(facts=facts[:3500]) if facts.strip() else "",
        scene_shape=shape,
        stock_rule=STOCK_RULE if stock else "",
    )


def plan_to_dict(plan: Plan) -> dict:
    return {
        "title": plan.title, "description": plan.description, "tags": plan.tags, "visual_style": plan.visual_style,
        "scenes": [{"narration": s.narration, "image": s.image_prompt, **({"stock": s.stock_query} if s.stock_query else {})}
                   for s in plan.scenes],
    }


def plan_state(plan: Plan) -> dict:
    return {"plan": plan_to_dict(plan), "language": plan.language, "fmt": plan.fmt, "sources": [list(x) for x in plan.sources],
            "facts": plan.facts, "target": plan.target}


def plan_from_state(d: dict, fmt: str | None = None) -> Plan:
    p = parse_plan(json.dumps(d["plan"], ensure_ascii=False), d.get("language", "hindi"), fmt or d.get("fmt", "shorts"))
    p.sources = [tuple(x) for x in d.get("sources") or []]
    p.facts = d.get("facts", "")
    p.target = int(d.get("target", 0))
    return p


def build_edit_prompt(plan: Plan, instruction: str, duration: int, stock: bool = False) -> str:
    shape = '{"narration": "...", "image": "..."' + (', "stock": "..."' if stock else "") + "}"
    return (
        "You are editing a YouTube video script. Here is the current plan as JSON:\n"
        + json.dumps(plan_to_dict(plan), ensure_ascii=False)
        + f"\n\nThe user's change request: {instruction.strip()[:500]}\n"
        "Apply it and return the FULL updated plan as ONLY valid JSON in the same shape "
        f'(scenes items look like {shape}). Keep the narration language ({LANG_INSTR.get(plan.language, "")}). '
        f"Keep about {scene_count(duration)} scenes unless asked otherwise. Keep facts accurate."
    )


def _extract_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise VideoError("script JSON nahi mila")
    raw = t[i : j + 1]
    for candidate in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except ValueError:
            continue
    raise VideoError("script JSON padh nahi paaya")


def parse_plan(text: str, language: str = "hindi", fmt: str = "shorts") -> Plan:
    data = _extract_json(text)
    scenes: list[Scene] = []
    for s in data.get("scenes") or []:
        if not isinstance(s, dict):
            continue
        narr = " ".join(str(s.get("narration") or "").split())
        img = " ".join(str(s.get("image") or s.get("image_prompt") or "").split())
        stock = " ".join(str(s.get("stock") or "").split())[:80]
        if narr and (img or stock):
            scenes.append(Scene(narr[:400], (img or stock)[:500], stock_query=stock))
    if len(scenes) < 2:
        raise VideoError("script me kam scenes aaye")
    tags = [str(t).strip().lstrip("#") for t in (data.get("tags") or []) if str(t).strip()][:15]
    return Plan(
        title=" ".join(str(data.get("title") or "Video").split())[:100],
        description=str(data.get("description") or "").strip()[:2000],
        tags=tags,
        visual_style=" ".join(str(data.get("visual_style") or "").split())[:300],
        scenes=scenes[:14],
        language=language,
        fmt=fmt,
    )


async def _llm_plan(deps: Deps, prompt: str, language: str, fmt: str) -> Plan:
    for i in range(3):
        try:
            return parse_plan(await deps.llm(prompt if i == 0 else prompt + "\nIMPORTANT: output ONLY the complete JSON object."), language, fmt)
        except VideoError:
            if i == 2:
                raise
    raise VideoError("script JSON nahi mila")


async def make_plan(
    topic: str, deps: Deps, *, language: str = "hindi", fmt: str = "shorts", duration: int = 45,
    stock: bool = False, research: bool = False, previous: Plan | None = None, instruction: str | None = None,
    progress: Progress = _noop,
) -> Plan:
    fmt = fmt if fmt in FORMATS else "shorts"
    duration = max(MIN_DURATION, min(MAX_DURATION, int(duration)))
    if previous is not None and instruction:
        await progress("✏️ Script badal raha hoon...")
        plan = await _llm_plan(deps, build_edit_prompt(previous, instruction, duration, stock), language, fmt)
        plan.sources, plan.facts, plan.target = previous.sources, previous.facts, duration
        return plan
    facts, sources = "", []
    if research and deps.research is not None:
        await progress("🔎 Pehle research kar raha hoon...")
        pack = await deps.research.gather(topic, deps.llm)
        facts, sources = pack.facts, pack.sources
    await progress("📝 Script likh raha hoon...")
    plan = await _llm_plan(deps, build_plan_prompt(topic, language, fmt, duration, facts, stock), language, fmt)
    plan.sources, plan.facts, plan.target = sources, facts, duration
    return plan


# ---------------------------------------------------------------- captions + srt
def split_captions(text: str, max_words: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    cur: list[str] = []
    for w in words:
        cur.append(w)
        end_of_phrase = w[-1:] in ",.!?;:।"
        if len(cur) >= max_words or (end_of_phrase and len(cur) >= max(2, max_words // 2)):
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        if chunks and len(cur) == 1:
            chunks[-1] += " " + cur[0]
        else:
            chunks.append(" ".join(cur))
    return chunks


def caption_timeline(text: str, seconds: float, max_words: int) -> list[tuple[float, float, str]]:
    """(start, end, text) per caption chunk, timed by length of the text."""
    return [(a, b, t) for a, b, _, t in cp.caption_states(cp.estimate_words(text, seconds), max_words, "plain")]


def build_srt(scenes: list[Scene], max_words: int) -> str:
    out: list[str] = []
    offset, n = 0.0, 1
    for sc in scenes:
        words = sc.words or cp.estimate_words(sc.narration, sc.audio_sec)
        text, n = cp.build_srt(words, max_words, offset, n)
        if text:
            out.append(text)
        offset += sc.duration
    return "\n".join(out)


# ---------------------------------------------------------------- rendering
def _motion(i: int, n_frames: int) -> str:
    n = max(1, n_frames)
    c = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    kind = i % 4
    if kind == 0:
        return f"z='1.0+0.22*on/{n}':{c}"
    if kind == 1:
        return f"z='1.22-0.22*on/{n}':{c}"
    if kind == 2:
        return f"z='1.2':x='(iw-iw/zoom)*on/{n}':y='ih/2-(ih/zoom/2)'"
    return f"z='1.2':x='(iw-iw/zoom)*(1-on/{n})':y='ih/2-(ih/zoom/2)'"


def remix_image(src: Path, dst: Path, k: int) -> Path:
    """Free 'edit' of an existing picture so a re-used image looks like a new shot:
    mirror, zoom into a different part, and shift the colours a little."""
    from PIL import ImageEnhance, ImageOps

    with Image.open(src) as im:
        im = im.convert("RGB")
        if k % 2:
            im = ImageOps.mirror(im)
        w, h = im.size
        z = (0.72, 0.8, 0.86)[k % 3]
        cw, ch = int(w * z), int(h * z)
        spots = ((0, 0), (1, 0), (0, 1), (1, 1), (0.5, 0.5))
        fx, fy = spots[k % len(spots)]
        x0, y0 = int((w - cw) * fx), int((h - ch) * fy)
        im = im.crop((x0, y0, x0 + cw, y0 + ch)).resize((w, h), Image.LANCZOS)
        im = ImageEnhance.Color(im).enhance((1.15, 0.9, 1.05, 1.25)[k % 4])
        im = ImageEnhance.Brightness(im).enhance((1.0, 1.06, 0.94)[k % 3])
        im.save(dst, "JPEG", quality=92)
    return dst


def fill_missing(scenes: list, workdir: Path) -> None:
    """Scenes without a picture get an edited copy of the nearest picture that did get made."""
    have = [i for i, sc in enumerate(scenes) if sc.image_path is not None or sc.stock_path is not None]
    pics = [i for i in have if scenes[i].image_path is not None]
    for i, sc in enumerate(scenes):
        if sc.image_path is not None or sc.stock_path is not None or not pics:
            continue
        j = min(pics, key=lambda p: (abs(p - i), p))
        try:
            sc.image_path = remix_image(scenes[j].image_path, workdir / f"remix_{i}.jpg", i + 1)
        except Exception as e:  # noqa: BLE001
            log.warning("remix_failed scene=%s err=%s", i, e)
            sc.image_path = scenes[j].image_path


def _prep_image(src: Path, dst: Path, w: int, h: int) -> None:
    with Image.open(src) as im:
        cover(im, w * 2, h * 2).save(dst, "JPEG", quality=92)


def caption_geometry(w: int, h: int) -> tuple[int, int, int]:
    """(caption box height, font size, y position)."""
    cap_h = int(h * 0.2)
    size = int(min(w, h) * 0.068)
    bottom = int(h * (0.1 if h > w else 0.06))
    return cap_h, size, h - cap_h - bottom


def make_track(words: list[Word], total: float, w: int, h: int, workdir: Path, name: str, mode: str = "word") -> Path | None:
    cap_h, size, _ = caption_geometry(w, h)
    max_words = 5 if h > w else 8
    states = cp.caption_states(words, max_words, "plain" if mode == "plain" else "word")
    return cp.write_track(states, total, w, cap_h, size, workdir, name)


def overlay_chain(base_label: str, track_input_idx: int, y: int, out_label: str = "vout") -> str:
    return (f"[{track_input_idx}:v]format=rgba,fps={FPS}[cap];"
            f"[{base_label}][cap]overlay=x=0:y={y}:eof_action=pass:format=auto[{out_label}]")


async def render_scene(i: int, scene: Scene, track: Path | None, w: int, h: int, workdir: Path) -> Path:
    total = scene.duration
    n_frames = max(1, int(round(total * FPS)))
    _, _, y = caption_geometry(w, h)
    if scene.stock_path is not None:
        inputs = ["-stream_loop", "-1", "-i", str(scene.stock_path)]
        base = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={FPS},"
                f"format=yuv420p[v0]")
    else:
        img2x = workdir / f"img2x_{i}.jpg"
        await asyncio.to_thread(_prep_image, scene.image_path, img2x, w, h)
        inputs = ["-i", str(img2x)]
        base = f"[0:v]zoompan={_motion(i, n_frames)}:d={n_frames}:s={w}x{h}:fps={FPS},format=yuv420p[v0]"
    inputs += ["-i", str(scene.audio_path)]
    parts = [base]
    last = "v0"
    if track is not None:
        inputs += ["-f", "concat", "-safe", "0", "-i", str(track)]
        parts.append(overlay_chain("v0", 2, y))
        last = "vout"
    parts.append("[1:a]aresample=44100,apad[a]")
    out = workdir / f"scene_{i}.mp4"
    await run_ffmpeg(
        inputs
        + ["-filter_complex", ";".join(parts), "-map", f"[{last}]", "-map", "[a]",
           "-t", f"{total:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100", str(out)]
    )
    return out


async def concat_clips(clips: list[Path], out: Path, workdir: Path) -> None:
    lst = workdir / "list.txt"
    lst.write_text("".join("file '" + str(c).replace("\\", "/").replace("'", "'\\''") + "'\n" for c in clips), encoding="utf-8")
    await run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)])


async def add_music(video: Path, music: Path, out: Path, volume: float = 0.12) -> None:
    await run_ffmpeg(
        ["-i", str(video), "-stream_loop", "-1", "-i", str(music), "-filter_complex",
         f"[1:a]volume={volume}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
    )


async def normalize_audio(video: Path, workdir: Path) -> None:
    """Bring speech to a normal YouTube loudness (about -16 LUFS); picture is copied untouched."""
    out = workdir / "norm.mp4"
    await run_ffmpeg(["-i", str(video), "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                      "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(out)])
    shutil.move(str(out), video)


def pick_music() -> Path | None:
    return pick_folder_music()


def clean_outputs(out_dir: Path, keep: int = 6) -> None:
    files = sorted(out_dir.glob("video_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[keep * 3 :]:  # mp4 + srt + thumb per video
        try:
            p.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- orchestration
async def _word_timing(deps: Deps, sc: Scene, data: bytes, ext: str) -> list[Word]:
    """Exact word times from speech-to-text if available, else spread by length."""
    voices = deps.voices
    if getattr(voices, "stt_enabled", False) and hasattr(voices, "transcribe_verbose"):
        try:
            tr = await voices.transcribe_verbose(data, f"scene.{ext}")
            if tr.words:
                return cp.align_words(sc.narration, tr.words, sc.audio_sec)
        except Exception as e:  # noqa: BLE001
            log.info("word_timing_fallback err=%s", type(e).__name__)
    return cp.estimate_words(sc.narration, sc.audio_sec)


async def render_plan(
    plan: Plan, deps: Deps, *, voice: str = "hindi-female", style: str | None = None, music: bool = False,
    stock: bool = False, captions: str = "word", progress: Progress = _noop,
) -> VideoResult:
    if not ffmpeg_available():
        raise VideoError("ffmpeg nahi mila. pip install imageio-ffmpeg chalao.")
    fmt = plan.fmt if plan.fmt in FORMATS else "shorts"
    w, h, size_name = FORMATS[fmt]
    deps.out_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="uwvid_"))
    t0 = time.time()
    n = len(plan.scenes)
    use_stock = bool(stock and deps.stock is not None and getattr(deps.stock, "enabled", False))
    try:
        done = {"v": 0, "i": 0}

        async def report() -> None:
            await progress(f"🎙 Awaaz {done['v']}/{n}  ·  {'🎞 Footage' if use_stock else '🖼 Images'} {done['i']}/{n}")

        async def do_voice(i: int, sc: Scene, rate: int = 0) -> None:
            data, ext = await deps.voices.synth(sc.narration, voice, rate)
            p = workdir / f"voice_{i}.{ext}"
            p.write_bytes(data)
            sc.audio_path = p
            sc.audio_sec = await media_seconds(p)
            sc.words = await _word_timing(deps, sc, data, ext) if captions == "word" else cp.estimate_words(sc.narration, sc.audio_sec)
            done["v"] += 1
            await report()

        seed = random.randint(1, 2_000_000)
        used: set[str] = set()
        portrait = fmt == "shorts"

        async def do_visual(i: int, sc: Scene) -> None:
            if use_stock and sc.stock_query:
                clip = await deps.stock.find(sc.stock_query, portrait, workdir, "video", min_seconds=4.0, exclude=used)
                if clip is None:
                    clip = await deps.stock.find(sc.stock_query, portrait, workdir, "image", exclude=used)
                if clip is not None:
                    if clip.kind == "video":
                        sc.stock_path = clip.path
                    else:
                        sc.image_path = clip.path
                    sc.stock_credit = clip.credit
                    if deps.usage is not None:
                        deps.usage.add("stock")
                    done["i"] += 1
                    await report()
                    return
            if deps.images is None or not getattr(deps.images, "enabled", True):
                done["i"] += 1
                return
            last: Exception | None = None
            for _ in range(3):
                try:
                    data = await deps.images.generate(
                        f"{plan.visual_style}. {sc.image_prompt}", seed=seed + i, size=size_name, style=style,
                        enhance=False, no_text=True,
                    )
                    p = workdir / f"img_{i}.jpg"
                    p.write_bytes(data)
                    sc.image_path = p
                    if deps.usage is not None:
                        deps.usage.add("images")
                    done["i"] += 1
                    await report()
                    return
                except Exception as e:  # retry, then fall back to a neighbour's picture
                    last = e
                    await asyncio.sleep(1.5)
            log.warning("video_image_failed scene=%s err=%s", i, last)
            done["i"] += 1

        await report()
        results = await asyncio.gather(
            *[do_voice(i, s) for i, s in enumerate(plan.scenes)],
            *[do_visual(i, s) for i, s in enumerate(plan.scenes)],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, BaseException):
                raise VideoError(f"voice ya visual nahi bana: {type(r).__name__}: {str(r)[:120]}")
        want = plan.target
        got = sum(s.duration for s in plan.scenes)
        if want and got > want * 1.12:  # too long: speak a bit faster (up to +30%)
            rate = min(30, int((got / want - 1) * 100) + 3)
            await progress(f"⏱ Video lambi hai ({got:.0f}s), awaaz {rate}% tez kar raha hoon...")
            await asyncio.gather(*[do_voice(i, s, rate) for i, s in enumerate(plan.scenes)])
        missing = [i for i, sc in enumerate(plan.scenes) if sc.image_path is None and sc.stock_path is None]
        stock_ok = deps.stock is not None and getattr(deps.stock, "enabled", False)
        if missing and len(missing) == n and stock_ok:  # no AI picture at all -> real footage / photos
            await progress("⚠ AI images nahi bani, Pexels/Pixabay se footage le raha hoon...")
            for i in missing:
                sc = plan.scenes[i]
                q = sc.stock_query or plan.title
                try:
                    clip = await deps.stock.find(q, portrait, workdir, "video", min_seconds=4.0, exclude=used) \
                        or await deps.stock.find(q, portrait, workdir, "image", exclude=used)
                except Exception as e:  # noqa: BLE001
                    log.warning("stock_fallback_failed scene=%s err=%s", i, e)
                    clip = None
                if clip is not None:
                    if clip.kind == "video":
                        sc.stock_path = clip.path
                    else:
                        sc.image_path = clip.path
                    sc.stock_credit = clip.credit
        elif missing and len(missing) < n:
            await progress(f"✂️ {len(missing)} image nahi bani, bani hui images ko edit karke laga raha hoon...")
        fill_missing(plan.scenes, workdir)  # remaining gaps -> edited copy of a nearby picture
        prev = None
        for sc in list(plan.scenes) + list(reversed(plan.scenes)):  # only stock clips left -> reuse a clip
            if sc.image_path is None and sc.stock_path is None:
                sc.stock_path = prev
            prev = sc.stock_path or prev
        if any(sc.image_path is None and sc.stock_path is None for sc in plan.scenes):
            raise VideoError("images nahi ban paayi — Pollinations credit khatam. Free backup ke liye .env me "
                             "CF_ACCOUNT_ID aur CF_API_TOKEN (Cloudflare) daalo, ya Pexels/Pixabay key.")

        clips: list[Path] = []
        for i, sc in enumerate(plan.scenes):
            await progress(f"🎞 Video bana raha hoon {i + 1}/{n} (thoda time lagega)...")
            track = await asyncio.to_thread(make_track, sc.words, sc.duration, w, h, workdir, f"cap{i}", captions)
            clips.append(await render_scene(i, sc, track, w, h, workdir))
        stamp = time.strftime("%Y%m%d_%H%M%S")
        final = deps.out_dir / f"video_{stamp}.mp4"
        await progress("🔗 Jod raha hoon...")
        await concat_clips(clips, final, workdir)
        total = sum(s.duration for s in plan.scenes)
        if music:
            m = None
            if deps.music is not None:
                m = await deps.music.get(plan.visual_style or plan.title, total, workdir)
            m = m or pick_music()
            if m:
                mixed = workdir / "mixed.mp4"
                try:
                    await add_music(final, m, mixed)
                    shutil.move(str(mixed), final)
                except VideoError as e:
                    log.warning("music_mix_failed err=%s", e)
        try:
            await normalize_audio(final, workdir)
        except VideoError as e:
            log.warning("loudnorm_failed err=%s", e)
        max_words = 5 if fmt == "shorts" else 8
        srt = final.with_suffix(".srt")
        srt.write_text(build_srt(plan.scenes, max_words), encoding="utf-8")

        thumb = None
        try:
            first = plan.scenes[0].image_path
            if first is None:  # stock-video first scene: grab a frame
                first = workdir / "frame0.jpg"
                await run_ffmpeg(["-ss", "1", "-i", str(plan.scenes[0].stock_path), "-frames:v", "1", str(first)])
            with Image.open(first) as im:
                import io as _io

                buf = _io.BytesIO()
                cover(im, 1280, 720).save(buf, "JPEG", quality=92)
            thumb = await asyncio.to_thread(overlay_title, buf.getvalue(), plan.title, None, "thumb")
        except Exception as e:
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
        credits = sorted({s.stock_credit for s in plan.scenes if s.stock_credit})
        log.info("video_done scenes=%s sec=%.0f took=%.0fs", n, total, time.time() - t0)
        return VideoResult(final, srt, plan, total, thumb, final.stat().st_size / 1e6, qc, credits)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def final_description(plan: Plan, credits: list[str]) -> str:
    """Description for YouTube: script description + sources + footage credits."""
    d = plan.description.strip()
    if plan.sources:
        d += "\n\nSources:\n" + "\n".join(f"- {t}: {u}" for t, u in plan.sources)
    if credits:
        d += "\n\nFootage: " + "; ".join(credits)
    return d[:4900]


async def produce_video(
    topic: str, deps: Deps, *, language: str = "hindi", fmt: str = "shorts", duration: int = 45,
    voice: str = "hindi-female", style: str | None = None, music: bool = False, stock: bool = False,
    research: bool = False, captions: str = "word", progress: Progress = _noop,
) -> VideoResult:
    plan = await make_plan(topic, deps, language=language, fmt=fmt, duration=duration, stock=stock, research=research, progress=progress)
    return await render_plan(plan, deps, voice=voice, style=style, music=music, stock=stock, captions=captions, progress=progress)
