"""Jobs for Milestone 4: AI script writing / revision, storyboard draft, scene regeneration.
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

    async def storyboard_draft(ctx: JobContext) -> dict:
        pid = int(ctx.inputs["project_id"])
        async with ctx.stage("draft", ctx.inputs) as st:
            if not st.skipped:
                await ctx.progress(0.2, "storyboard bana raha hai")
                state = await hub.storyboards.generate_draft(pid, use_ai=bool(ctx.inputs.get("use_ai", True)),
                                                             replace_approved=bool(ctx.inputs.get("replace", False)))
                st.result = {"scenes": len(hub.storyboards.scenes(pid)), "source": state.get("source", "")}
            return dict(st.result)

    async def scene_regen(ctx: JobContext) -> dict:
        async with ctx.stage("regen", ctx.inputs) as st:
            if not st.skipped:
                s = await hub.storyboards.regenerate_scene(int(ctx.inputs["project_id"]), int(ctx.inputs["scene_id"]),
                                                           ctx.inputs.get("instruction", ""))
                st.result = {"scene": s["scene_number"]}
            return dict(st.result)

    hub.jobs.register("script_write", script_write, max_attempts=2, title="AI script")
    hub.jobs.register("storyboard_draft", storyboard_draft, max_attempts=2, title="Storyboard draft")
    hub.jobs.register("scene_regen", scene_regen, max_attempts=2, title="Scene dobara (AI)")
