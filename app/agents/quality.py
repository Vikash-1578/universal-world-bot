"""Agent 5: Quality Checker Agent - Final review of tone, language, and flow."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging

log = logging.getLogger("app.agents.quality")

class QualityAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        script = input_data.get("script", "")
        log.info("Performing final quality check for project %d...", project_id)
        
        prompt = (
            f"You are the Head of Content at Verinomia. Review the following YouTube script for:\n"
            f"1. Brand Tone: Does it sound mysterious, curious, and knowledgeable?\n"
            f"2. Hinglish Balance: Is the mix of Hindi and English natural and engaging?\n"
            f"3. Flow: Is the transition between sections smooth?\n\n"
            f"If the script is perfect, reply with 'QUALITY_PASSED'. Otherwise, provide specific corrections.\n\n"
            f"Script:\n{script}"
        )
        review = await self.hub.llm.generate(prompt)
        
        return {"script": script, "review": review, "passed": "QUALITY_PASSED" in review.upper()}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        return output_data.get("passed", False)
