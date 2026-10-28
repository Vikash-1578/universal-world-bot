"""Output validation (master prompt section 18): open the file with ffprobe (or ffmpeg as fallback) and check
streams, resolution, frame rate and duration. File-level checks only — they say nothing about artistic quality."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.observability.diagnostics import find_ffmpeg, find_ffprobe


async def _run(cmd: list[str], timeout: float = 60) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "timeout"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def probe(settings: Settings, path: str | Path) -> dict[str, Any]:
    path = str(path)
    ffmpeg = find_ffmpeg(settings)
    ffprobe = find_ffprobe(ffmpeg)
    info: dict[str, Any] = {"path": path, "exists": Path(path).exists(), "video": None, "audio": None, "duration": 0.0}
    if not info["exists"]:
        return info
    info["bytes"] = Path(path).stat().st_size
    if ffprobe:
        code, out, _ = await _run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
        if code == 0:
            j = json.loads(out or "{}")
            for s in j.get("streams", []):
                if s.get("codec_type") == "video" and info["video"] is None:
                    num, _, den = str(s.get("avg_frame_rate", "0/1")).partition("/")
                    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
                    info["video"] = {"codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height"),
                                     "fps": round(fps, 3)}
                elif s.get("codec_type") == "audio" and info["audio"] is None:
                    info["audio"] = {"codec": s.get("codec_name"), "sample_rate": int(s.get("sample_rate") or 0),
                                     "channels": s.get("channels")}
            info["duration"] = float(j.get("format", {}).get("duration") or 0)
            info["readable"] = True
            return info
    if ffmpeg:  # fallback: parse `ffmpeg -i` banner
        _, _, err = await _run([ffmpeg, "-hide_banner", "-i", path])
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
        if m:
            info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
        v = re.search(r"Video: (\w+).*?, (\d{2,5})x(\d{2,5}).*?([\d.]+) fps", err)
        if v:
            info["video"] = {"codec": v[1], "width": int(v[2]), "height": int(v[3]), "fps": float(v[4])}
        a = re.search(r"Audio: (\w+), (\d+) Hz", err)
        if a:
            info["audio"] = {"codec": a[1], "sample_rate": int(a[2]), "channels": None}
        info["readable"] = bool(m)
    return info


def check(info: dict, *, width: int | None = None, height: int | None = None, fps: float | None = None,
          min_seconds: float = 0.5, max_seconds: float | None = None, need_audio: bool = True) -> list[str]:
    """Return a list of problems (empty = valid)."""
    problems = []
    if not info.get("exists"):
        return ["file nahi bani"]
    if not info.get("readable"):
        problems.append("file khul nahi rahi")
    v = info.get("video")
    if not v:
        problems.append("video stream nahi hai")
    else:
        if width and height and (v.get("width"), v.get("height")) != (width, height):
            problems.append(f"size {v.get('width')}x{v.get('height')} hai, chahiye {width}x{height}")
        if fps and abs((v.get("fps") or 0) - fps) > 0.5:
            problems.append(f"fps {v.get('fps')} hai, chahiye {fps}")
    if need_audio and not info.get("audio"):
        problems.append("audio stream nahi hai")
    d = info.get("duration") or 0
    if d < min_seconds:
        problems.append(f"video bahut chhoti hai ({d:.1f}s)")
    if max_seconds and d > max_seconds:
        problems.append(f"video lambi hai ({d:.0f}s > {max_seconds:.0f}s)")
    return problems
