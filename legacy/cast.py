"""Character voices: a few real TTS voices + rate/pitch changes = many different-sounding characters."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.voice import VOICES, VoiceError


@dataclass(frozen=True)
class CastVoice:
    key: str
    label: str  # shown on the button
    base: str  # key in voice.VOICES
    rate: int  # percent
    pitch: int  # Hz
    lang: str  # hindi | english
    gender: str  # m | f
    kind: str  # child | adult | old | narrator | creature


def _v(key, label, base, rate, pitch, lang, gender, kind) -> CastVoice:
    return CastVoice(key, label, base, rate, pitch, lang, gender, kind)


PRESETS: dict[str, CastVoice] = {c.key: c for c in [
    # ---- Hindi
    _v("hi-narrator", "Narrator (Hindi)", "hindi-male", -3, 0, "hindi", "m", "narrator"),
    _v("hi-man", "Aadmi", "hindi-male", 0, 0, "hindi", "m", "adult"),
    _v("hi-woman", "Aurat", "hindi-female", 0, 0, "hindi", "f", "adult"),
    _v("hi-boy", "Ladka (bachcha)", "hindi-male", 10, 35, "hindi", "m", "child"),
    _v("hi-girl", "Ladki (bachchi)", "hindi-female", 12, 30, "hindi", "f", "child"),
    _v("hi-old-man", "Buddha baba", "hindi-male", -14, -18, "hindi", "m", "old"),
    _v("hi-old-woman", "Buddhi dadi", "hindi-female", -12, -22, "hindi", "f", "old"),
    _v("hi-lion", "Sher / raja (bhaari)", "hindi-male", -10, -32, "hindi", "m", "creature"),
    _v("hi-tiny", "Chuha / chhota jaanwar", "hindi-female", 18, 55, "hindi", "f", "creature"),
    _v("hi-comic", "Mazaakiya", "hindi-male", 8, 18, "hindi", "m", "creature"),
    _v("hi-villain", "Khalnayak", "hindi-male", -6, -40, "hindi", "m", "adult"),
    # ---- English
    _v("en-narrator", "Narrator (English)", "english-male", -3, 0, "english", "m", "narrator"),
    _v("en-man", "Man", "english-male", 0, 0, "english", "m", "adult"),
    _v("en-woman", "Woman", "english-female", 0, 0, "english", "f", "adult"),
    _v("en-boy", "Boy", "kids", 6, 18, "english", "m", "child"),
    _v("en-girl", "Girl", "kids", 4, 8, "english", "f", "child"),
    _v("en-old-man", "Old man", "india-male", -14, -18, "english", "m", "old"),
    _v("en-old-woman", "Grandma", "india-female", -12, -20, "english", "f", "old"),
    _v("en-lion", "Lion / big beast", "english-male", -10, -35, "english", "m", "creature"),
    _v("en-tiny", "Mouse / tiny animal", "kids", 16, 50, "english", "f", "creature"),
    _v("en-comic", "Funny sidekick", "india-male", 8, 18, "english", "m", "creature"),
    _v("en-villain", "Villain", "english-male", -6, -42, "english", "m", "adult"),
]}


def for_lang(lang: str) -> list[CastVoice]:
    return [c for c in PRESETS.values() if c.lang == lang]


def get(key: str | None, lang: str = "hindi") -> CastVoice:
    if key in PRESETS:
        return PRESETS[key]
    return PRESETS["hi-narrator" if lang == "hindi" else "en-narrator"]


def pick(lang: str, gender: str = "m", kind: str = "adult", hint: str = "") -> CastVoice:
    """Best preset for a character (used when the story writer gives no valid voice)."""
    pre = "hi" if lang == "hindi" else "en"
    h = hint.lower()
    if any(w in h for w in ("mouse", "chuha", "chuhiya", "rabbit", "sparrow", "squirrel", "tiny", "bird", "chidiya")):
        return PRESETS[f"{pre}-tiny"]
    if any(w in h for w in ("lion", "sher", "tiger", "bear", "elephant", "bhalu", "hathi", "king", "raja")):
        return PRESETS[f"{pre}-lion"]
    if kind == "child":
        return PRESETS[f"{pre}-{'boy' if gender == 'm' else 'girl'}"]
    if kind == "old":
        return PRESETS[f"{pre}-old-{'man' if gender == 'm' else 'woman'}"]
    if kind == "narrator":
        return PRESETS[f"{pre}-narrator"]
    return PRESETS[f"{pre}-{'man' if gender == 'm' else 'woman'}"]


def cycle(key: str, lang: str, step: int = 1) -> str:
    keys = [c.key for c in for_lang(lang)]
    if key not in keys:
        return keys[0]
    return keys[(keys.index(key) + step) % len(keys)]


# Natural engines: Gemini voice + how to speak, per preset (key without the "hi-"/"en-" prefix).
GEMINI_MAP: dict[str, tuple[str, str]] = {
    "narrator": ("Charon", "Narrate warmly and clearly like a storyteller"),
    "man": ("Orus", "Say naturally like a friendly man"),
    "woman": ("Sulafat", "Say warmly like a caring woman"),
    "boy": ("Puck", "Say like a small excited boy"),
    "girl": ("Leda", "Say like a cheerful little girl"),
    "old-man": ("Algenib", "Say slowly like a wise old man"),
    "old-woman": ("Gacrux", "Say gently like a kind old grandmother"),
    "lion": ("Algenib", "Say in a deep, powerful, slow voice like a big lion king"),
    "tiny": ("Zephyr", "Say quickly in a tiny squeaky voice like a little mouse"),
    "comic": ("Sadachbia", "Say in a funny, playful way"),
    "villain": ("Alnilam", "Say in a slow, menacing villain voice"),
}
EMOTION_WORDS = {"happy": "happily", "sad": "sadly", "angry": "angrily", "scared": "in a scared, shaky voice",
                 "surprised": "with surprise"}
ENGINES = ("elevenlabs", "gemini", "edge")


def _role(key: str) -> str:
    return key.split("-", 1)[1] if "-" in key else key


def eleven_choose(voices: list[dict], c: CastVoice, used: set[str]) -> str | None:
    """Pick an ElevenLabs voice for a preset by its labels (gender / age), different from voices already used."""
    if not voices:
        return None
    want_g = "female" if c.gender == "f" else "male"
    want_age = {"child": ("young",), "old": ("old",), "narrator": ("middle", "old")}.get(c.kind, ("young", "middle"))

    def score(v: dict) -> int:
        sc = 0
        sc += 4 if v["gender"] == want_g else 0
        sc += 2 if any(a in v["age"] for a in want_age) else 0
        sc += 1 if ("indian" in v["accent"] or "hindi" in v["accent"]) and c.lang == "hindi" else 0
        sc += 1 if c.kind == "creature" and any(w in v["desc"] for w in ("deep", "raspy", "squeaky", "funny", "animated")) else 0
        sc -= 5 if v["id"] in used else 0
        return sc

    best = max(voices, key=score)
    return best["id"]


async def say(voices, text: str, key: str, lang: str = "hindi", emotion: str = "", engine: str = "edge",
              eleven_id: str | None = None) -> tuple[bytes, str]:
    """Speak `text` with a cast voice -> (audio bytes, ext). Natural engines fall back to edge on any error."""
    c = get(key, lang)
    if c.base not in VOICES:
        raise VoiceError("unknown base voice " + c.base)
    if engine == "elevenlabs" and eleven_id and getattr(voices, "eleven_enabled", False):
        try:
            return await voices.eleven_tts(text, eleven_id, emotional=bool(emotion)), "mp3"
        except Exception:  # noqa: BLE001
            pass
    if engine == "gemini" and getattr(voices, "gemini_enabled", False):
        gv, style = GEMINI_MAP.get(_role(c.key), ("Kore", ""))
        if emotion in EMOTION_WORDS:
            style = f"{style}, {EMOTION_WORDS[emotion]}" if style else f"Say {EMOTION_WORDS[emotion]}"
        try:
            return await voices.gemini_styled(text, gv, style), "wav"
        except Exception:  # noqa: BLE001
            pass
    if c.pitch:
        return await voices.synth(text, c.base, c.rate, c.pitch)
    return await voices.synth(text, c.base, c.rate)


async def pick_engine(voices, lang: str = "hindi") -> str:
    """Best natural engine that works right now (one tiny test call), else edge. STORY_VOICE env can force one."""
    import os

    forced = (os.environ.get("STORY_VOICE") or "").strip().lower()
    if forced in ENGINES:
        return forced
    probe = "नमस्ते" if lang == "hindi" else "Hello"
    if getattr(voices, "eleven_enabled", False):
        try:
            vs = await voices.eleven_voices()
            if vs:
                await voices.eleven_tts(probe, vs[0]["id"])
                return "elevenlabs"
        except Exception:  # noqa: BLE001
            pass
    if getattr(voices, "gemini_enabled", False):
        try:
            await voices.gemini_styled(probe, "Kore", "")
            return "gemini"
        except Exception:  # noqa: BLE001
            pass
    return "edge"


async def tune(data: bytes, ext: str, semis: int = 0, speed: int = 0) -> tuple[bytes, str]:
    """Change pitch (semitones) and speed (percent) of any voice -> many different voices from one."""
    if not semis and not speed:
        return data, ext
    import tempfile
    from pathlib import Path

    from app.services.media import run_ffmpeg

    f = 2 ** (semis / 12.0)
    tempo = (1 + speed / 100.0) / f
    chain = []
    while tempo > 2.0:
        chain.append("atempo=2.0")
        tempo /= 2.0
    while tempo < 0.5:
        chain.append("atempo=0.5")
        tempo /= 0.5
    chain.append(f"atempo={tempo:.4f}")
    af = f"aresample=44100,asetrate={44100 * f:.0f},aresample=44100," + ",".join(chain)
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / f"in.{ext}", Path(td) / "out.wav"
        src.write_bytes(data)
        await run_ffmpeg(["-i", str(src), "-af", af, "-ac", "1", "-c:a", "pcm_s16le", str(dst)], timeout=120)
        return dst.read_bytes(), "wav"


def tune_label(semis: int, speed: int) -> str:
    return f"pitch {semis:+d} · speed {speed:+d}%"


ENGINE_LABEL = {"elevenlabs": "ElevenLabs (sabse natural)", "gemini": "Gemini (natural)", "edge": "Edge (basic)"}


VARIANTS = [("", 0, 0), ("patli", 3, 0), ("bhaari", -3, 0), ("tez", 1, 15), ("dheemi", -1, -12), ("bachkani", 5, 8),
            ("gehri", -5, -6)]


def _voice_library() -> list[dict]:
    out = []
    for key, c in PRESETS.items():
        for vname, semis, speed in VARIANTS:
            out.append({"id": f"{key}{'.' + vname if vname else ''}", "preset": key, "semis": semis, "speed": speed, "lang": c.lang,
                        "name": c.label + (f" · {vname}" if vname else "")})
    return out


VOICE_LIBRARY: list[dict] = _voice_library()


def voices_for(lang: str) -> list[dict]:
    return [v for v in VOICE_LIBRARY if v["lang"] == lang]


def voice_id(preset: str, semis: int, speed: int) -> str | None:
    return next((v["id"] for v in VOICE_LIBRARY if v["preset"] == preset and v["semis"] == semis and v["speed"] == speed), None)


def next_voice(lang: str, preset: str, semis: int, speed: int, step: int = 1) -> dict:
    lib = voices_for(lang)
    cur = voice_id(preset, semis, speed)
    ids = [v["id"] for v in lib]
    i = ids.index(cur) if cur in ids else next((k for k, v in enumerate(lib) if v["preset"] == preset), -1)
    return lib[(i + step) % len(lib)]


SAMPLE = {"hindi": "नमस्ते दोस्तों, मैं इस कहानी का किरदार हूँ। कैसी लग रही है मेरी आवाज़?",
          "english": "Hello friends, I am a character in this story. How does my voice sound?"}
