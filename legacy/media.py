"""ffmpeg helpers shared by every media feature."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path


class VideoError(RuntimeError):
    pass


def ffmpeg_exe() -> str:
    p = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise VideoError("ffmpeg nahi mila (pip install imageio-ffmpeg)") from e


def ffmpeg_available() -> bool:
    try:
        ffmpeg_exe()
        return True
    except VideoError:
        return False


async def run_ffmpeg(args: list[str], timeout: float = 900.0) -> str:
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise VideoError("ffmpeg time out")
    if proc.returncode != 0:
        raise VideoError("ffmpeg error: " + err.decode("utf-8", "ignore")[-300:])
    return err.decode("utf-8", "ignore")


async def ffmpeg_info(args: list[str], timeout: float = 120.0) -> str:
    """Run ffmpeg and return stderr whatever the exit code (for -i probing and *detect filters)."""
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_exe(), "-hide_banner", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise VideoError("ffmpeg time out")
    return err.decode("utf-8", "ignore")


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


async def media_seconds(path: Path) -> float:
    err = await ffmpeg_info(["-i", str(path)], 60)
    m = _DUR_RE.search(err)
    if not m:
        raise VideoError("media length nahi mili")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
