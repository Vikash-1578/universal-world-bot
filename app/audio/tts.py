"""Text-to-Speech service using edge-tts (Free)."""
from __future__ import annotations

import logging
from pathlib import Path
import edge_tts

log = logging.getLogger("app.audio.tts")

class TTS:
    def __init__(self, default_voice: str = "hi-IN-MadhurNeural"):
        self.default_voice = default_voice

    async def synthesize(self, text: str, output_path: Path, voice: str = None) -> Path:
        """Converts text to speech audio file using edge-tts."""
        voice = voice or self.default_voice
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            return output_path
        except Exception as e:
            log.error("TTS synthesis failed: %s", e)
            raise e

    async def list_voices(self):
        """Returns list of available voices."""
        voices = await edge_tts.VoicesManager.create()
        return voices.voices
