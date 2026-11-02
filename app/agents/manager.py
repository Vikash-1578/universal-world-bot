"""Manager agent: runs research -> accuracy -> script -> quality (with at most 2 automatic revisions) as stages
of ONE resumable job. It never approves a script — the owner always does that in Script Studio."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents.base import Brief
from app.agents.accuracy import AccuracyAgent
from app.agents.evidence import EvidenceStore
from app.agents.live import Live
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
             f"Proof ke saath {kept} claims pass, {dropped} hataye (proof.md me links + quotes)",
             f"Quality score: {q['data']['score']}/100 · ~{q['data']['seconds']:.0f}s · {q['data']['scenes']} scenes"]
    if revisions:
        lines.append(f"Auto-badlaav: {revisions}")
    for i in q["data"]["issues"][:6]:
        lines.append(("❌ " if i["severity"] == "error" else "• ") + i["message"])
    lines.append("AI: " + (provider or "-"))
    lines.append("\n👉 Script Studio me padho, ek baar khud fact-check karo, phir Approve.")
    return "\n".join(lines)


def register(hub: "Hub") -> None:
    async def _pipeline(ctx: "JobContext", live: Live) -> dict:
        pid = int(ctx.inputs["project_id"])
        brief = Brief.from_project(hub, pid, ctx.inputs["topic"])
        if len(brief.topic) < 5:
            raise InvalidInput("Topic thoda aur likho.")
        research, scripts, quality = ResearchAgent(hub), ScriptAgent(hub), QualityAgent(hub)
        accuracy = AccuracyAgent(hub, research)
        research.notify = accuracy.notify = live.note
        accuracy.research.notify = live.note
        scripts.notify = live.note
        store = EvidenceStore(hub.projects.folder(pid, "agents", "sources"))

        async with ctx.stage("research", {"topic": brief.topic}) as st:
            await live.update("research", "running", "shuru", 0.05)
            if not st.skipped:
                await ctx.progress(0.1, "Research agent (web)")
                r = await research.run(brief, store)
                if not r.ok:
                    raise InvalidInput("Research me proof ke saath kaafi claims nahi mile. " + " ".join(r.notes))
                st.result = {"claims": r.data["claims"], "sources": r.data["sources"]}
            claims_raw = st.result["claims"]
            await live.update("research", "done", f"{st.result['sources']} pages, {len(claims_raw)} claims", 0.30)

        async with ctx.stage("accuracy", {"claims": [c["id"] for c in claims_raw], "n_sources": len(store.sources)}) as st:
            await live.update("accuracy", "running", "shuru", 0.32)
            if not st.skipped:
                await ctx.progress(0.3, "Accuracy agent (proof check)")
                a = await accuracy.run(brief, store, claims_raw)
                if not a.ok:
                    raise InvalidInput("Accuracy: " + " ".join(a.notes) + " Topic badlo ya aur specific likho.")
                st.result = {"kept": a.data["accepted"], "dropped": len(a.data["dropped"]), "disputed": len(a.data["disputed"])}
            kept, dropped = st.result["kept"], int(st.result["dropped"]) + int(st.result.get("disputed", 0))
            await live.update("accuracy", "done", f"{len(kept)} claims pass, {dropped} hataye", 0.55)

        async with ctx.stage("script", {"kept": kept, "topic": brief.topic}) as st:
            await live.update("script", "running", "script likh raha hoon (local AI, 1-3 min)", 0.58)
            if not st.skipped:
                await ctx.progress(0.5, "Script agent")
                st.result = (await scripts.run(brief, kept)).data
            script_id, provider = int(st.result["script_id"]), hub.llm.last_provider
            await live.update("script", "done", f"draft v{st.result['version']}", 0.75)

        facts_text = facts_to_notes(kept)
        revisions = 0
        while True:
            async with ctx.stage(f"quality{revisions}", {"script_id": script_id}) as st:
                await live.update("quality", "running", "script check ho rahi hai" + (f" (badlaav {revisions})" if revisions else ""), 0.8)
                if not st.skipped:
                    await ctx.progress(0.7 + 0.1 * revisions, "Quality checker")
                    q = quality.check(brief, hub.scripts.get(script_id)["content"], facts_text)
                    st.result = q.to_dict()
                q = st.result
            if q["ok"] or revisions >= MAX_REVISIONS:
                break
            revisions += 1
            await live.update("quality", "running", f"score {q['data']['score']} kam — script sudhaar raha hoon (badlaav {revisions})", 0.85)
            async with ctx.stage(f"revise{revisions}", {"script_id": script_id, "issues": q["data"]["issues"]}) as st:
                if not st.skipped:
                    from app.agents.base import AgentResult

                    instr = quality.revision_instruction(AgentResult("quality", data=q["data"]))
                    st.result = (await scripts.revise(brief, script_id, instr)).data
                script_id = int(st.result["script_id"])

        await live.update("quality", "done", f"score {q['data']['score']}/100" + (f", {revisions} badlaav" if revisions else ""), 1.0)
        version = hub.scripts.get(script_id)["version_number"]
        report = format_report(brief.topic, version, q, len(kept), dropped, revisions, provider)
        await ctx.progress(1.0, "Done")
        chat_id = ctx.job.get("chat_id")
        if hub.bot is not None and chat_id:
            try:
                await hub.bot.send_message(chat_id, report, parse_mode=None)
                proof = hub.projects.folder(pid, "agents") / "proof.md"
                if proof.exists():
                    from aiogram.types import BufferedInputFile

                    await hub.bot.send_document(chat_id, BufferedInputFile(proof.read_bytes(), filename="proof.md"),
                                                caption="📎 Proof pack — har claim ke links aur quotes", parse_mode=None)
            except Exception:  # noqa: BLE001 - report is also in the job output
                pass
        hub.audit.record("agent_pipeline", "ok", "project", pid, script=script_id, score=q["data"]["score"])
        return {"script_id": script_id, "version": version, "passed": bool(q["ok"]), "score": q["data"]["score"], "report": report}

    async def video_pipeline(ctx: "JobContext") -> dict:
        live = Live(hub, ctx.job.get("chat_id"), ctx.id, str(ctx.inputs.get("topic", "")))
        await live.update("research", "running", "shuru", 0.02)
        try:
            return await _pipeline(ctx, live)
        except Exception as e:  # noqa: BLE001 - show WHERE it stopped, then let the job fail normally
            why = getattr(e, "user_message", None) or str(e)
            await live.update(live.current, "failed", why[:80])
            chat_id = ctx.job.get("chat_id")
            if isinstance(e, InvalidInput) and hub.bot is not None and chat_id:
                try:
                    await hub.bot.send_message(chat_id, f"⚠️ Video #{ctx.id} ruk gayi:\n{why}", parse_mode=None)
                except Exception:  # noqa: BLE001
                    pass
            raise

    hub.jobs.register("video_pipeline", video_pipeline, max_attempts=1, title="Auto script (agents)")
