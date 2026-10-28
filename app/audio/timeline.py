"""One timeline for a scene: every spoken line becomes real audio; its start/end drive the mouth, the body
gestures and the subtitles. The scene WAV is assembled sample-exact, so audio and video lengths match.
"""
from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path
from typing import Callable

GAP = 0.3     # pause between lines
TAIL = 0.6    # breath after the last line
RATE = 44100


def _frames(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, RATE):
            raise ValueError(f"unexpected wav format in {path.name}")
        return w.readframes(w.getnframes())


def build_scene_audio(lines: list[dict], lead: float, out_wav: Path, make_line: Callable[[int, dict], Path],
                      min_seconds: float = 2.0, fps: int = 30) -> dict:
    """lines: [{"speaker", "text", "actor": bool, "emotion", "action"}] in script order.
    make_line(i, line) -> path of a 44.1 kHz mono 16-bit WAV for that line (TTS + voice style).
    Returns {"duration", "cues": [...]}; duration is rounded up to whole video frames."""
    pcm = bytearray()
    silence = lambda sec: b"\x00\x00" * int(round(sec * RATE))  # noqa: E731
    pcm += silence(lead)
    cues = []
    for i, ln in enumerate(lines):
        data = _frames(make_line(i, ln))
        start = len(pcm) / 2 / RATE
        pcm += data
        end = len(pcm) / 2 / RATE
        cues.append({**ln, "start": round(start, 3), "end": round(end, 3)})
        pcm += silence(GAP if i + 1 < len(lines) else TAIL)
    total = max(min_seconds, len(pcm) / 2 / RATE)
    total = math.ceil(total * fps - 1e-6) / fps
    need = int(round(total * RATE)) * 2
    pcm += b"\x00" * max(0, need - len(pcm))
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(pcm[:need]))
    return {"duration": round(total, 4), "cues": cues}


def rms_db(path: Path, start: float = 0.0, end: float | None = None) -> float:
    """Loudness (dBFS) of a part of a mono 16-bit WAV. -120 for digital silence."""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        w.setpos(int(start * sr))
        n = int(((end if end is not None else w.getnframes() / sr) - start) * sr)
        a = array("h")
        a.frombytes(w.readframes(max(0, n)))
    if not a:
        return -120.0
    ms = sum(x * x for x in a[::4]) / max(1, len(a[::4]))
    return 20 * math.log10(math.sqrt(ms) / 32768) if ms > 0 else -120.0


def srt_time(sec: float) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(cues: list[dict]) -> str:
    """cues with absolute start/end (seconds in the final video)."""
    out = []
    for n, c in enumerate(cues, 1):
        who = "" if not c.get("actor") else f"{c['speaker']}: "
        out += [str(n), f"{srt_time(c['start'])} --> {srt_time(c['end'])}", who + c["text"], ""]
    return "\n".join(out)


def parse_srt(text: str) -> list[tuple[float, float]]:
    def sec(t: str) -> float:
        hms, ms = t.strip().split(",")
        h, m, s = hms.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    spans = []
    for line in text.splitlines():
        if "-->" in line:
            a, b = line.split("-->")
            spans.append((sec(a), sec(b)))
    return spans
