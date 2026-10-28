"""Local, free text-to-speech with Piper (no API key, no cloud, runs on CPU).

* Engine: the `piper-tts` package (OHF-Voice/piper1-gpl, GPL-3.0) + ONNX voice files in data/models/piper.
  Windows wheels exist for Python 3.11-3.14 (piper-tts is abi3; onnxruntime has cp314 wheels).
* One base voice per language; every character gets its own "voice style" made from it by changing pitch and speed
  (owner's request). Styles are saved per project, so a character keeps its voice across renders.
* Cloud voices are NOT used here. (Any future cloud TTS must follow the Cloud AI opt-in in Settings.)
"""
from __future__ import annotations

import importlib.util
import subprocess
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.errors import HubError

if TYPE_CHECKING:
    from app.storage.db import Database

VOICE_PREF = {
    "hindi": ("hi_IN-pratham-medium", "hi_IN-priyamvada-medium", "hi_IN-rohan-medium"),
    "hinglish": ("hi_IN-pratham-medium", "hi_IN-priyamvada-medium", "hi_IN-rohan-medium"),
    "english": ("en_US-lessac-medium", "en_US-ryan-medium", "en_GB-alan-medium"),
}
DEFAULT_DOWNLOAD = {"hindi": "hi_IN-pratham-medium", "hinglish": "hi_IN-pratham-medium", "english": "en_US-lessac-medium"}


@dataclass(frozen=True)
class Style:
    name: str
    pitch: float  # semitones
    speed: float  # 1.0 = normal


NARRATOR = Style("Narrator", 0.0, 0.97)
STYLES = (
    Style("Bachcha (patli, tez)", 4.0, 1.08),
    Style("Bhaari aadmi", -3.5, 0.95),
    Style("Ladki (meethi)", 3.0, 1.02),
    Style("Buzurg (dheemi)", -5.0, 0.88),
    Style("Chulbula", 6.0, 1.12),
    Style("Normal", 1.5, 1.0),
    Style("Gambhir", -1.5, 0.93),
    Style("Nanha (bahut patli)", 7.5, 1.1),
)


class TTSUnavailable(HubError):
    code = "tts_unavailable"


def piper_installed() -> bool:
    return importlib.util.find_spec("piper") is not None


class PiperTTS:
    def __init__(self, voices_dir: Path) -> None:
        self.voices_dir = Path(voices_dir)
        self._loaded: dict[str, object] = {}
        self._lock = threading.Lock()

    def voices(self) -> list[str]:
        if not self.voices_dir.is_dir():
            return []
        return sorted(p.name[:-5] for p in self.voices_dir.glob("*.onnx") if (self.voices_dir / (p.name + ".json")).exists())

    def voice_for(self, language: str) -> str | None:
        have = self.voices()
        for v in VOICE_PREF.get(language, VOICE_PREF["hindi"]):
            if v in have:
                return v
        prefix = "en" if language == "english" else "hi"
        return next((v for v in have if v.startswith(prefix)), None)

    def check(self, language: str) -> str:
        """Voice name to use, or raise TTSUnavailable with exact fix steps."""
        if not piper_installed():
            raise TTSUnavailable("Awaaz (Piper TTS) install nahi hai.\nPowerShell me: .\\scripts\\install.ps1 -SkipConfig  (ya .\\scripts\\update.ps1)")
        v = self.voice_for(language)
        if not v:
            want = DEFAULT_DOWNLOAD.get(language, "hi_IN-pratham-medium")
            raise TTSUnavailable(f"{language} ki awaaz file nahi mili ({self.voices_dir}).\n"
                                 f"PowerShell me: .\\venv\\Scripts\\python -m piper.download_voices {want} --download-dir data\\models\\piper")
        return v

    def _voice(self, name: str):
        with self._lock:
            v = self._loaded.get(name)
            if v is None:
                from piper import PiperVoice

                v = PiperVoice.load(str(self.voices_dir / f"{name}.onnx"))
                self._loaded[name] = v
            return v

    def synth(self, text: str, voice: str, out_wav: Path) -> float:
        """Blocking. Writes a mono 16-bit WAV, returns its length in seconds."""
        v = self._voice(voice)
        with wave.open(str(out_wav), "wb") as wf:
            v.synthesize_wav(text, wf)  # type: ignore[attr-defined]
        return wav_seconds(out_wav)


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def apply_style(ffmpeg: str, src: Path, dst: Path, style: Style, rate: int = 44100) -> float:
    """Pitch + speed change of one line (ffmpeg), output 44.1 kHz mono 16-bit. Returns seconds."""
    with wave.open(str(src), "rb") as w:
        sr = w.getframerate()
    f = 2 ** (style.pitch / 12.0)
    chain = f"asetrate={int(sr * f)},aresample={rate},atempo={style.speed / f:.4f},loudnorm=I=-18:TP=-2:LRA=11,aresample={rate}"
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-af", chain, "-ac", "1", "-ar", str(rate),
                        "-c:a", "pcm_s16le", str(dst)], capture_output=True, timeout=120)
    if r.returncode != 0 or not dst.exists():
        raise HubError("Awaaz process nahi hui (FFmpeg).", detail=r.stderr.decode(errors="replace")[-300:])
    return wav_seconds(dst)


# ---------------------------------------------------------------- per-project voice choice
def voice_map(db: "Database", project_id: int) -> dict[str, int]:
    return dict(db.get_setting(f"voices:{int(project_id)}", {}) or {})


def assign(db: "Database", project_id: int, roles: list[str], hints: dict[str, dict] | None = None) -> dict[str, int]:
    """Give every speaking role a style index (kept once chosen). Hints: library profile (age / gender) per role."""
    cur = voice_map(db, project_id)
    used = set(cur.values())
    hints = hints or {}
    for role in roles:
        if role in cur:
            continue
        h = hints.get(role, {})
        age, gender = str(h.get("age", "")).lower(), str(h.get("gender", "")).lower()
        want = 0 if age in ("child", "kid", "bachcha") else 3 if age in ("old", "elder", "buzurg") else 2 if gender in ("f", "female") else None
        if want is None or want in used:
            want = next((i for i in range(len(STYLES)) if i not in used), len(cur) % len(STYLES))
        cur[role] = want
        used.add(want)
    db.set_setting(f"voices:{int(project_id)}", cur)
    return cur


def set_style(db: "Database", project_id: int, role: str, index: int) -> dict[str, int]:
    cur = voice_map(db, project_id)
    cur[role] = int(index) % len(STYLES)
    db.set_setting(f"voices:{int(project_id)}", cur)
    return cur


def style_of(vmap: dict[str, int], role: str | None) -> Style:
    if not role or "arrat" in role.lower() or role in ("नैरेटर", "कथावाचक"):
        return NARRATOR
    return STYLES[vmap.get(role, 5) % len(STYLES)]
