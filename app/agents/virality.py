"""Agent 4: Virality Agent - Checks script for hooks and retention."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging

log = logging.getLogger("app.agents.virality")

class ViralityAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        script = input_data.get("script", "")
        log.info("Checking virality and retention for project %d...", project_id)
        
        prompt = (
            f"Analyze this YouTube script for virality. Check: 1. Is the hook strong? 2. Is the pacing fast? 3. Is the language engaging?\n"
            f"If it's viral-ready, reply with 'VIRAL_OK'. If not, provide specific improvements.\n\n"
            f"Script:\n{script}"
        )
        analysis = await self.hub.llm.generate(prompt)
        
        return {"script": script, "analysis": analysis, "is_viral": "VIRAL_OK" in analysis.upper()}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        return output_data.get("is_viral", False)
