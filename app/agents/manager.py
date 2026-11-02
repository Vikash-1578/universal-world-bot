"""Manager agent: runs research -> fact-check -> script -> quality (with at most 2 automatic revisions) as stages
of ONE resumable job. It never approves a script — the owner always does that in Script Studio."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents.base import Brief
from app.agents.factcheck import FactCheckAgent
from app.agents.quality import QualityAgent
from app.agents.research import ResearchAgent
from app.agents.script import ScriptAgent, facts_to_notes
from app.core.errors import InvalidInput

if TYPE_CHECKING:
    from app.container import Hub
    from app.scheduler.service import JobContext

MAX_REVISIONS = 2


def format_report(topic: str, version: int, q: dict, kept: int, dropped: int, revisions: int, provider: str) -> str:
    icon = "✅" if q["ok"] else "⚠️"
    lines = [f"{icon} Auto script ready — v{version}", f"Topic: {topic[:100]}",
             f"Facts: {kept} rakhe, {dropped} hataye (model-memory based, sources se verify nahi)",
             f"Quality score: {q['data']['score']}/100 · ~{q['data']['seconds']:.0f}s · {q['data']['scenes']} scenes"]
    if revisions:
        lines.append(f"Auto-badlaav: {revisions}")
    for i in q["data"]["issues"][:6]:
        lines.append(("❌ " if i["severity"] == "error" else "• ") + i["message"])
    lines.append("AI: " + (provider or "-"))
    lines.append("\n👉 Script Studio me padho, ek baar khud fact-check karo, phir Approve.")
    return "\n".join(lines)


def register(hub: "Hub") -> None:
    async def video_pipeline(ctx: "JobContext") -> dict:
        pid = int(ctx.inputs["project_id"])
        brief = Brief.from_project(hub, pid, ctx.inputs["topic"])
        if len(brief.topic) < 5:
            raise InvalidInput("Topic thoda aur likho.")
        research, facts, scripts, quality = ResearchAgent(hub), FactCheckAgent(hub), ScriptAgent(hub), QualityAgent(hub)

        async with ctx.stage("research", {"topic": brief.topic}) as st:
            if not st.skipped:
                await ctx.progress(0.1, "Research agent")
                r = await research.run(brief)
                if not r.ok:
                    raise InvalidInput("Research me kaafi points nahi mile. " + " ".join(r.notes))
                st.result = {"research": r.data}
            research_data = st.result["research"]

        async with ctx.stage("factcheck", {"research": research_data}) as st:
            if not st.skipped:
                await ctx.progress(0.3, "Fact-check agent")
                f = await facts.verify_points(brief, research_data)
                if not f.ok:
                    raise InvalidInput("Fact-check ke baad 3 se kam pakke points bache — topic badlo ya specific likho.")
                st.result = {"kept": f.data["kept"], "dropped": len(f.data["dropped"])}
            kept, dropped = st.result["kept"], int(st.result["dropped"])

        async with ctx.stage("script", {"kept": kept, "topic": brief.topic}) as st:
            if not st.skipped:
                await ctx.progress(0.5, "Script agent")
                st.result = (await scripts.run(brief, kept)).data
            script_id, provider = int(st.result["script_id"]), hub.llm.last_provider

        facts_text = facts_to_notes(kept)
        revisions = 0
        while True:
            async with ctx.stage(f"quality{revisions}", {"script_id": script_id}) as st:
                if not st.skipped:
                    await ctx.progress(0.7 + 0.1 * revisions, "Quality checker")
                    q = quality.check(brief, hub.scripts.get(script_id)["content"], facts_text)
                    st.result = q.to_dict()
                q = st.result
            if q["ok"] or revisions >= MAX_REVISIONS:
                break
            revisions += 1
            async with ctx.stage(f"revise{revisions}", {"script_id": script_id, "issues": q["data"]["issues"]}) as st:
                if not st.skipped:
                    from app.agents.base import AgentResult

                    instr = quality.revision_instruction(AgentResult("quality", data=q["data"]))
                    st.result = (await scripts.revise(brief, script_id, instr)).data
                script_id = int(st.result["script_id"])

        version = hub.scripts.get(script_id)["version_number"]
        report = format_report(brief.topic, version, q, len(kept), dropped, revisions, provider)
        await ctx.progress(1.0, "Done")
        chat_id = ctx.job.get("chat_id")
        if hub.bot is not None and chat_id:
            try:
                await hub.bot.send_message(chat_id, report, parse_mode=None)
            except Exception:  # noqa: BLE001 - report is also in the job output
                pass
        hub.audit.record("agent_pipeline", "ok", "project", pid, script=script_id, score=q["data"]["score"])
        return {"script_id": script_id, "version": version, "passed": bool(q["ok"]), "score": q["data"]["score"], "report": report}

    hub.jobs.register("video_pipeline", video_pipeline, max_attempts=1, title="Auto script (agents)")
