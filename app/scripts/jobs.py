"""Jobs: AI script writing / revision.
They run in the scheduler so Telegram never waits on an AI call."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.scheduler.service import JobContext

if TYPE_CHECKING:
    from app.container import Hub


def register(hub: "Hub") -> None:
    async def script_write(ctx: JobContext) -> dict:
        pid = int(ctx.inputs["project_id"])
        async with ctx.stage("write", ctx.inputs) as st:
            if not st.skipped:
                await ctx.progress(0.2, "AI script likh raha hai")
                if ctx.inputs.get("story"):
                    v = await hub.scripts.story_to_script(pid, ctx.inputs["story"])
                elif ctx.inputs.get("revise_script_id"):
                    v = await hub.scripts.revise_with_ai(int(ctx.inputs["revise_script_id"]), ctx.inputs["text"])
                else:
                    v = await hub.scripts.write_with_ai(pid, ctx.inputs["text"])
                st.result = {"script_id": v["id"], "version": v["version_number"], "provider": hub.llm.last_provider}
            return dict(st.result)

    hub.jobs.register("script_write", script_write, max_attempts=2, title="AI script")
