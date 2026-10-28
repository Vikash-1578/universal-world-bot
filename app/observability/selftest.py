"""A real (non-mock) end-to-end job used by diagnostics: three stages, a checkpoint, and an FFmpeg render of a
2-second test clip. Proves the scheduler + FFmpeg actually work on this machine."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.scheduler.service import JobContext

if TYPE_CHECKING:
    from app.container import Hub


def register(hub: "Hub") -> None:
    async def selftest(ctx: JobContext) -> dict:
        from app.observability.diagnostics import find_ffmpeg

        async with ctx.stage("prepare", {"v": 1}) as st:
            if not st.skipped:
                await ctx.progress(0.2, "prepare")
                st.result = {"ok": True}
        async with ctx.stage("render_test_clip", {"v": 1}) as st:
            if not st.skipped:
                exe = find_ffmpeg(hub.settings)
                if not exe:
                    from app.core.errors import HubError

                    raise HubError("FFmpeg nahi mila, test video nahi ban saki.")
                out = ctx.workdir / "selftest.mp4"
                proc = await asyncio.create_subprocess_exec(
                    exe, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(out), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
                _, err = await asyncio.wait_for(proc.communicate(), timeout=120)
                if proc.returncode != 0 or not out.exists():
                    from app.core.errors import HubError

                    raise HubError("FFmpeg test render fail hua.", detail=err.decode(errors="replace")[-300:])
                await ctx.progress(0.8, "render_test_clip")
                st.result = {"path": str(out), "bytes": out.stat().st_size}
            clip = st.result
        async with ctx.stage("validate", clip) as st:
            if not st.skipped:
                from app.exports.validate import probe

                info = await probe(hub.settings, clip["path"])
                st.result = {"duration": info.get("duration"), "video": info.get("video"), "audio": info.get("audio")}
            return {"clip": clip, "probe": st.result}

    hub.jobs.register("selftest", selftest, heavy=False, max_attempts=2, title="System self-test (FFmpeg)")
