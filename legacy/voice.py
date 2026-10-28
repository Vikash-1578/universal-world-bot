"""Voice: text -> speech (TTS) and speech -> text (STT).

TTS engines are tried in order (default: edge, gemini, pollinations):
  edge         free, no key, good Hindi + English voices  (pip: edge-tts)
  gemini       Gemini TTS with your Gemini key
  pollinations OpenAI-style /v1/audio/speech with your Pollinations key
STT: Groq Whisper (free) -> Pollinations whisper.

Every call is best-effort and falls through to the next engine.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import wave
from dataclasses import dataclass, field

import aiohttp

from app.services.captions import Word
from app.utils.logging import get_logger

log = get_logger(__name__)

GEMINI_HOST = "https://generativelanguage.googleapis.com/v1beta"
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
ELEVEN_HOST = "https://api.elevenlabs.io"
POLLINATIONS_HOST = "https://gen.pollinations.ai"
MAX_TTS_CHARS = 2500
MAX_AUDIO_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class Voice:
    label: str
    edge: str
    gemini: str
    openai: str
    lang: str  # hindi | english


VOICES: dict[str, Voice] = {
    "hindi-female": Voice("Hindi (female)", "hi-IN-SwaraNeural", "Kore", "nova", "hindi"),
    "hindi-male": Voice("Hindi (male)", "hi-IN-MadhurNeural", "Puck", "onyx", "hindi"),
    "english-female": Voice("English US (female)", "en-US-AriaNeural", "Kore", "nova", "english"),
    "english-male": Voice("English US (male)", "en-US-GuyNeural", "Puck", "onyx", "english"),
    "india-female": Voice("English India (female)", "en-IN-NeerjaNeural", "Kore", "nova", "english"),
    "india-male": Voice("English India (male)", "en-IN-PrabhatNeural", "Puck", "onyx", "english"),
    "kids": Voice("Kids friendly (English)", "en-US-AnaNeural", "Leda", "shimmer", "english"),
}
DEFAULT_VOICE = {"hindi": "hindi-female", "english": "english-female"}


class VoiceError(RuntimeError):
    pass


@dataclass
class Transcript:
    text: str
    segments: list[tuple[float, float, str]] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    language: str | None = None
    duration: float = 0.0


def resolve_voice(name: str | None, language: str = "hindi") -> str:
    n = (name or "").strip().lower()
    return n if n in VOICES else DEFAULT_VOICE.get(language, "hindi-female")


def pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


class VoiceService:
    def __init__(
        self,
        *,
        gemini_keys: list[str] | None = None,
        pollinations_keys: list[str] | None = None,
        groq_keys: list[str] | None = None,
        engines: str | None = None,
        timeout: float = 60.0,
        gemini_host: str = GEMINI_HOST,
        groq_url: str = GROQ_STT_URL,
        pollinations_host: str = POLLINATIONS_HOST,
        gemini_models: tuple[str, ...] = ("gemini-2.5-flash-preview-tts", "gemini-3.1-flash-tts-preview"),
        stt_model: str = "whisper-large-v3-turbo",
    ) -> None:
        self._gemini = [k for k in (gemini_keys or []) if k]
        self._poll = [k for k in (pollinations_keys or []) if k]
        self._groq = [k for k in (groq_keys or []) if k]
        order = (engines or os.environ.get("VOICE_ENGINES") or "edge,gemini,pollinations").split(",")
        self._engines = [e.strip().lower() for e in order if e.strip()]
        self._timeout = timeout
        self._gemini_host = gemini_host.rstrip("/")
        self._groq_url = groq_url
        self._poll_host = pollinations_host.rstrip("/")
        self._gemini_models = gemini_models
        self._stt_model = stt_model
        self._sem = asyncio.Semaphore(3)
        self.usage = None  # optional UsageTracker
        self._eleven = [k.strip() for k in (os.environ.get("ELEVENLABS_API_KEY") or "").split(",") if k.strip()]
        self._eleven_host = ELEVEN_HOST
        self._eleven_voices: list[dict] | None = None

    @property
    def eleven_enabled(self) -> bool:
        return bool(self._eleven)

    @property
    def gemini_enabled(self) -> bool:
        return bool(self._gemini)

    # ------------------------------------------------------------ natural voices (stories)
    async def eleven_voices(self) -> list[dict]:
        """Voices this ElevenLabs account can use: [{id, name, gender, age, accent}]."""
        if self._eleven_voices is not None:
            return self._eleven_voices
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        out: list[dict] = []
        async with aiohttp.ClientSession(timeout=timeout) as s:
            for key in self._eleven:
                async with s.get(f"{self._eleven_host}/v1/voices", headers={"xi-api-key": key}) as r:
                    if r.status != 200:
                        continue
                    j = await r.json(content_type=None)
                for v in j.get("voices") or []:
                    lab = v.get("labels") or {}
                    out.append({"id": v.get("voice_id"), "name": v.get("name", ""), "gender": str(lab.get("gender", "")).lower(),
                                "age": str(lab.get("age", "")).lower(), "accent": str(lab.get("accent", "")).lower(),
                                "desc": (str(lab.get("description", "")) + " " + str(lab.get("descriptive", ""))).lower()})
                break
        self._eleven_voices = [v for v in out if v["id"]]
        return self._eleven_voices

    async def eleven_tts(self, text: str, voice_id: str, emotional: bool = False) -> bytes:
        text = " ".join((text or "").split())[:MAX_TTS_CHARS]
        body = {"text": text, "model_id": os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
                "voice_settings": {"stability": 0.3 if emotional else 0.45, "similarity_boost": 0.75, "style": 0.35 if emotional else 0.15}}
        last = "no elevenlabs key"
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with self._sem, aiohttp.ClientSession(timeout=timeout) as s:
            for key in self._eleven:
                async with s.post(f"{self._eleven_host}/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                                  json=body, headers={"xi-api-key": key}) as r:
                    data = await r.read()
                    if r.status == 200 and data:
                        if self.usage is not None:
                            self.usage.add("tts_chars", len(text))
                        return data
                    last = f"http {r.status} {data[:120]!r}"
        raise VoiceError("elevenlabs: " + last)

    async def gemini_styled(self, text: str, voice_name: str, style: str = "") -> bytes:
        """Gemini TTS with a spoken-style instruction ("Say like a scared little boy: ...")."""
        text = " ".join((text or "").split())[:MAX_TTS_CHARS]
        v = Voice("x", "", voice_name, "", "")
        async with self._sem:
            return await self._gemini_tts(f"{style}: {text}" if style else text, v)

    @property
    def tts_enabled(self) -> bool:
        return True  # edge needs no key; failures just fall through

    @property
    def stt_enabled(self) -> bool:
        return bool(self._groq or self._poll)

    # ------------------------------------------------------------ TTS
    async def synth(self, text: str, voice: str = "hindi-female", rate: int = 0, pitch: int = 0) -> tuple[bytes, str]:
        """Return (audio bytes, extension) -- 'mp3' or 'wav'."""
        text = " ".join((text or "").split())[:MAX_TTS_CHARS]
        if not text:
            raise VoiceError("empty text")
        if self.usage is not None:
            self.usage.add("tts_chars", len(text))
        v = VOICES.get(voice) or VOICES["hindi-female"]
        errors: list[str] = []
        async with self._sem:
            for eng in self._engines:
                try:
                    if eng == "edge":
                        return await self._edge(text, v, rate, pitch), "mp3"
                    if eng == "gemini" and self._gemini:
                        return await self._gemini_tts(text, v), "wav"
                    if eng == "pollinations" and self._poll:
                        return await self._poll_tts(text, v), "mp3"
                except Exception as e:  # try the next engine
                    errors.append(f"{eng}:{type(e).__name__}")
                    log.warning("tts_engine_failed engine=%s err=%s %s", eng, type(e).__name__, str(e)[:120])
        raise VoiceError("no TTS engine worked (" + ", ".join(errors or ["none configured"]) + ")")

    async def _edge(self, text: str, v: Voice, rate: int, pitch: int = 0) -> bytes:
        import edge_tts  # lazy: optional dependency

        async def run() -> bytes:
            comm = edge_tts.Communicate(text, v.edge, rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz")
            buf = bytearray()
            async for chunk in comm.stream():
                if chunk.get("type") == "audio":
                    buf.extend(chunk["data"])
            if not buf:
                raise VoiceError("edge returned no audio")
            return bytes(buf)

        return await asyncio.wait_for(run(), self._timeout)

    async def _gemini_tts(self, text: str, v: Voice) -> bytes:
        body = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v.gemini}}},
            },
        }
        last = "no gemini key"
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            for key in self._gemini:
                for model in self._gemini_models:
                    url = f"{self._gemini_host}/models/{model}:generateContent"
                    async with s.post(url, json=body, headers={"x-goog-api-key": key}) as r:
                        if r.status != 200:
                            last = f"http {r.status}"
                            continue
                        j = await r.json(content_type=None)
                    try:
                        part = j["candidates"][0]["content"]["parts"][0]["inlineData"]
                        pcm = base64.b64decode(part["data"])
                    except (KeyError, IndexError, TypeError, ValueError):
                        last = "no audio in reply"
                        continue
                    rate = 24000
                    mime = str(part.get("mimeType", ""))
                    if "rate=" in mime:
                        try:
                            rate = int(mime.split("rate=")[1].split(";")[0])
                        except ValueError:
                            pass
                    return pcm_to_wav(pcm, rate)
        raise VoiceError(last)

    async def _poll_tts(self, text: str, v: Voice) -> bytes:
        last = "http error"
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            for key in self._poll:
                payload = {"model": "openai/tts-1", "input": text[:4000], "voice": v.openai}
                async with s.post(
                    f"{self._poll_host}/v1/audio/speech", json=payload, headers={"Authorization": f"Bearer {key}"}
                ) as r:
                    ctype = (r.headers.get("Content-Type") or "").lower()
                    if r.status == 200 and ctype.startswith("audio/"):
                        data = await r.read()
                        if data:
                            return data
                    last = f"http {r.status}"
        raise VoiceError(last)

    # ------------------------------------------------------------ STT
    async def transcribe(self, audio: bytes, filename: str = "voice.ogg", language: str | None = None) -> str:
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise VoiceError("bad audio size")
        if not (self._groq or self._poll):
            raise VoiceError("no speech-to-text key (add a groq key)")
        last = "failed"
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        targets = [(self._groq_url, k, self._stt_model) for k in self._groq] + [
            (f"{self._poll_host}/v1/audio/transcriptions", k, "openai/whisper-large-v3") for k in self._poll
        ]
        async with aiohttp.ClientSession(timeout=timeout) as s:
            for url, key, model in targets:
                form = aiohttp.FormData()
                form.add_field("file", audio, filename=filename, content_type="application/octet-stream")
                form.add_field("model", model)
                form.add_field("response_format", "json")
                if language:
                    form.add_field("language", language)
                try:
                    async with s.post(url, data=form, headers={"Authorization": f"Bearer {key}"}) as r:
                        if r.status != 200:
                            last = f"http {r.status}"
                            continue
                        j = await r.json(content_type=None)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    last = type(e).__name__
                    continue
                text = (j.get("text") if isinstance(j, dict) else "") or ""
                if text.strip():
                    return text.strip()
                last = "empty transcript"
        raise VoiceError(last)

    async def transcribe_verbose(self, audio: bytes, filename: str = "audio.mp3", language: str | None = None) -> Transcript:
        """Speech-to-text WITH timestamps (segments + words). Groq Whisper; other engines give text only."""
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise VoiceError("bad audio size")
        if not (self._groq or self._poll):
            raise VoiceError("no speech-to-text key (add a groq key)")
        timeout = aiohttp.ClientTimeout(total=max(self._timeout, 180.0))
        async with aiohttp.ClientSession(timeout=timeout) as s:
            for key in self._groq:
                form = aiohttp.FormData()
                form.add_field("file", audio, filename=filename, content_type="application/octet-stream")
                form.add_field("model", self._stt_model)
                form.add_field("response_format", "verbose_json")
                form.add_field("timestamp_granularities[]", "word")
                form.add_field("timestamp_granularities[]", "segment")
                if language:
                    form.add_field("language", language)
                try:
                    async with s.post(self._groq_url, data=form, headers={"Authorization": f"Bearer {key}"}) as r:
                        if r.status != 200:
                            continue
                        j = await r.json(content_type=None)
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    continue
                tr = parse_verbose(j)
                if tr.text.strip():
                    if self.usage is not None:
                        self.usage.add("stt_seconds", tr.duration or 0)
                    return tr
        # no timestamps available from the other engines
        text = await self.transcribe(audio, filename, language)
        return Transcript(text=text)


def parse_verbose(j: dict) -> Transcript:
    words = [Word(str(w.get("word", "")).strip(), float(w.get("start", 0)), float(w.get("end", 0)))
             for w in (j.get("words") or []) if str(w.get("word", "")).strip()]
    segs = [(float(x.get("start", 0)), float(x.get("end", 0)), str(x.get("text", "")).strip())
            for x in (j.get("segments") or []) if str(x.get("text", "")).strip()]
    return Transcript(str(j.get("text", "")).strip(), segs, words, j.get("language"), float(j.get("duration") or 0))
