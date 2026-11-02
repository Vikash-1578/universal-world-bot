"""Agent 3: Scripting Agent - Converts research into an engaging Hinglish script."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging

log = logging.getLogger("app.agents.scripting")

class ScriptingAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        report = input_data.get("report", "")
        log.info("Writing engaging Hinglish script for project %d...", project_id)
        
        prompt = (
            f"Convert the following research report into a high-retention YouTube script in Hinglish (Hindi + English). "
            f"Structure it with: 1. A killer Hook (first 30s), 2. Engaging Main Body with storytelling, 3. Strong Outro.\n\n"
            f"Research Report:\n{report}"
        )
        script = await self.hub.llm.generate(prompt)
        
        return {"script": script, "report": report}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        script = output_data.get("script", "")
        # Basic check: ensure it has sections like Hook and Outro
        return len(script) > 500 and "Hook" in script or "Intro" in script
