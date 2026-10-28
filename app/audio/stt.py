"""Speech-to-text for voice messages.

* Local: not installed by default (a local Whisper model is a large download — Model Manager, Milestone 9).
* Cloud: Groq Whisper, only when Cloud AI is ON and a `groq:` key exists. The owner is told the audio goes to Groq.
"""
from __future__ import annotations

import asyncio

import aiohttp

from app.core.errors import HubError, ProviderUnavailable

GROQ_STT = "https://api.groq.com/openai/v1/audio/transcriptions"


class STTUnavailable(HubError):
    code = "stt_unavailable"


async def transcribe(data: bytes, filename: str, *, keys: list[str], cloud_enabled: bool, language: str = "") -> str:
    if not cloud_enabled or not keys:
        raise STTUnavailable(
            "Voice ko text me badalne ke liye abhi koi engine chalu nahi hai.\n"
            "• ⚙️ Settings me Cloud AI ON karo (keys.txt me groq: key chahiye) — awaaz Groq ko jayegi\n"
            "• Local Whisper Model Manager (Milestone 9) me aayega\n"
            "• Ya story text me likh ke bhejo")
    last = ""
    for key in keys:
        form = aiohttp.FormData()
        form.add_field("file", data, filename=filename, content_type="audio/ogg")
        form.add_field("model", "whisper-large-v3")
        if language in ("hi", "en"):
            form.add_field("language", language)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
                async with s.post(GROQ_STT, data=form, headers={"Authorization": f"Bearer {key}"}) as r:
                    body = await r.json(content_type=None)
                    if r.status == 200 and body.get("text"):
                        return str(body["text"]).strip()
                    last = f"http {r.status}"
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            last = type(e).__name__
    raise ProviderUnavailable("Voice text me nahi badal payi, thodi der baad try karo.", detail=last)
