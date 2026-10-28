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
        a = re.search(r"Audio: (\w+)[^\n]*?, (\d+) Hz", err)
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


async def _decoded_seconds(ffmpeg: str, path: str, sel: str) -> float:
    """Decode one stream fully and read the last 'time=' — works without ffprobe."""
    code, _, err = await _run([ffmpeg, "-hide_banner", "-stats", "-i", path, "-map", sel, "-f", "null", "-"], timeout=300)
    times = re.findall(r"time=(\d+):(\d+):([\d.]+)", err)
    if code != 0 or not times:
        return 0.0
    hh, mm, ss = times[-1]
    return int(hh) * 3600 + int(mm) * 60 + float(ss)


async def loudness(settings: Settings, path: str | Path) -> dict[str, float]:
    ffmpeg = find_ffmpeg(settings)
    if not ffmpeg:
        return {}
    _, _, err = await _run([ffmpeg, "-hide_banner", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"], timeout=300)
    out = {}
    for k in ("mean_volume", "max_volume"):
        m = re.search(k + r": (-?[\d.]+) dB", err)
        if m:
            out[k] = float(m.group(1))
    return out


async def check_av(settings: Settings, path: str | Path, *, expected_seconds: float | None = None,
                   srt_text: str | None = None, min_max_db: float = -40.0, tolerance: float = 0.25) -> tuple[list[str], dict]:
    """Audio / video / subtitle timeline checks: silent audio, audio-vs-video length mismatch, length vs the planned
    timeline, and subtitles that run past the end. Returns (problems, measurements)."""
    ffmpeg = find_ffmpeg(settings)
    problems: list[str] = []
    if not ffmpeg:
        return ["FFmpeg nahi mila — awaaz check nahi ho saka"], {}
    path = str(path)
    v = await _decoded_seconds(ffmpeg, path, "0:v:0")
    a = await _decoded_seconds(ffmpeg, path, "0:a:0")
    lv = await loudness(settings, path)
    m = {"video_seconds": round(v, 3), "audio_seconds": round(a, 3), **lv}
    if lv.get("max_volume", -120.0) < min_max_db:
        problems.append(f"awaaz khaali hai (silent, max {lv.get('max_volume', -120):.0f} dB)")
    if not a:
        problems.append("audio stream padhi nahi gayi")
    elif abs(v - a) > tolerance:
        problems.append(f"audio ({a:.2f}s) aur video ({v:.2f}s) ki lambai alag hai")
    if expected_seconds and abs(v - expected_seconds) > max(tolerance, 0.02 * expected_seconds):
        problems.append(f"video {v:.2f}s hai, timeline {expected_seconds:.2f}s thi")
    if srt_text is not None:
        from app.audio.timeline import parse_srt

        spans = parse_srt(srt_text)
        m["subtitles"] = len(spans)
        if not spans:
            problems.append("subtitles khaali hain")
        elif spans[-1][1] > v + 0.05:
            problems.append("subtitles video ke khatam hone ke baad tak chal rahe hain")
        elif any(b <= a2 for a2, b in spans):
            problems.append("subtitle timing galat (end <= start)")
    return problems, m
