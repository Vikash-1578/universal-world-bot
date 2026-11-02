"""Script agent: checked facts -> narration script (a new draft version; never approves anything)."""
from __future__ import annotations

from app.agents.base import Agent, AgentResult, Brief


def facts_to_notes(kept: list[dict]) -> str:
    return "\n".join(f"- {c['text']}" for c in kept)


class ScriptAgent(Agent):
    name = "script"
    role = "Checked facts -> script draft"

    async def run(self, brief: Brief, kept: list[dict]) -> AgentResult:
        v = await self.hub.scripts.write_with_ai(brief.project_id, brief.topic, notes=facts_to_notes(kept))
        res = AgentResult(self.name, data={"script_id": v["id"], "version": v["version_number"]}, provider=self.hub.llm.last_provider)
        self.save(brief.project_id, res)
        return res

    async def revise(self, brief: Brief, script_id: int, instruction: str) -> AgentResult:
        v = await self.hub.scripts.revise_with_ai(script_id, instruction)
        res = AgentResult(self.name, data={"script_id": v["id"], "version": v["version_number"]}, provider=self.hub.llm.last_provider)
        self.save(brief.project_id, res)
        return res
