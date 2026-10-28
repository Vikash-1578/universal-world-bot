"""Background music: your own folder -> Gemini Lyria (if it works) -> a calm pad synthesized by ffmpeg (always works)."""
from __future__ import annotations

import base64
import os
import random
from pathlib import Path

import aiohttp

from app.services.media import VideoError, run_ffmpeg
from app.utils.logging import get_logger

log = get_logger(__name__)

GEMINI_HOST = "https://generativelanguage.googleapis.com/v1beta"
CHORDS = {  # Hz
    "calm": (110.0, 164.81, 220.0, 277.18),
    "happy": (130.81, 164.81, 196.0, 261.63),
    "dramatic": (98.0, 116.54, 146.83, 196.0),
}
MOODS = {
    "calm": ("calm", "peaceful", "relax", "nature"),
    "happy": ("happy", "kids", "fun", "cartoon", "cute", "play"),
    "dramatic": ("dramatic", "history", "war", "mystery", "dark", "epic", "horror"),
}


def pick_mood(text: str) -> str:
    low = (text or "").lower()
    for mood, words in MOODS.items():
        if any(w in low for w in words):
            return mood
    return "calm"


def pick_folder_music(folder: str | None = None) -> Path | None:
    d = folder if folder is not None else os.environ.get("VIDEO_MUSIC_DIR", "")
    if not d or not Path(d).is_dir():
        return None
    files = [p for p in Path(d).iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")]
    return random.choice(files) if files else None


async def synth_pad(out: Path, seconds: float, mood: str = "calm") -> Path:
    """Soft ambient chord pad (4 sine waves, tremolo, low-pass, fades). Not a song, but royalty-free and offline."""
    seconds = max(5.0, min(float(seconds), 600.0))
    freqs = CHORDS.get(mood, CHORDS["calm"])
    args: list[str] = []
    for f in freqs:
        args += ["-f", "lavfi", "-i", f"sine=frequency={f}:sample_rate=44100:duration={seconds:.2f}"]
    fade_out = max(0.0, seconds - 3)
    flt = (
        "[0][1][2][3]amix=inputs=4:normalize=0,tremolo=f=0.25:d=0.35,lowpass=f=1200,"
        f"afade=t=in:d=2,afade=t=out:st={fade_out:.2f}:d=3,volume=0.55,aformat=channel_layouts=stereo[a]"
    )
    await run_ffmpeg(args + ["-filter_complex", flt, "-map", "[a]", "-c:a", "pcm_s16le", str(out)], timeout=120)
    return out


class MusicService:
    def __init__(self, gemini_keys: list[str] | None = None, folder: str | None = None,
                 lyria_models: tuple[str, ...] = ("lyria-3-clip-preview",), timeout: float = 90.0,
                 use_lyria: bool | None = None) -> None:
        self._keys = [k for k in (gemini_keys or []) if k]
        self._folder = folder
        self._models = lyria_models
        self._timeout = timeout
        self._lyria = (os.environ.get("MUSIC_LYRIA", "1") != "0") if use_lyria is None else use_lyria

    async def _lyria_clip(self, prompt: str, out: Path) -> Path | None:
        """Best effort: the exact Lyria request shape is not verified, so any failure just falls through."""
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["AUDIO"]}}
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            for model in self._models:
                for key in self._keys:
                    url = f"{GEMINI_HOST}/models/{model}:generateContent"
                    try:
                        async with s.post(url, json=body, headers={"x-goog-api-key": key}) as r:
                            if r.status != 200:
                                continue
                            j = await r.json(content_type=None)
                    except (aiohttp.ClientError, TimeoutError):
                        continue
                    for cand in j.get("candidates", []):
                        for part in (cand.get("content") or {}).get("parts", []):
                            inline = part.get("inlineData") or part.get("inline_data")
                            if inline and "audio" in (inline.get("mimeType") or inline.get("mime_type") or ""):
                                mime = inline.get("mimeType") or inline.get("mime_type")
                                ext = "wav" if "wav" in mime else "mp3"
                                p = out.with_suffix("." + ext)
                                p.write_bytes(base64.b64decode(inline["data"]))
                                return p
        return None

    async def get(self, mood_text: str, seconds: float, workdir: Path) -> Path | None:
        f = pick_folder_music(self._folder)
        if f:
            return f
        mood = pick_mood(mood_text)
        if self._keys and self._lyria:
            try:
                p = await self._lyria_clip(f"{mood} instrumental background music, no vocals, loopable, for a video about: {mood_text[:100]}", workdir / "lyria")
                if p:
                    return p
            except Exception as e:  # noqa: BLE001
                log.warning("lyria_failed err=%s", type(e).__name__)
        try:
            return await synth_pad(workdir / "pad.wav", seconds, mood)
        except VideoError as e:
            log.warning("pad_failed err=%s", e)
            return None
