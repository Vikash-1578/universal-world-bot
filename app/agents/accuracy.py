"""Agent 2: Accuracy Agent - Cross-verifies facts."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging

log = logging.getLogger("app.agents.accuracy")

class AccuracyAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        report = input_data.get("report", "")
        log.info("Verifying accuracy of report...")
        
        # Agent 2 takes the report and asks LLM to find inconsistencies or fake facts
        prompt = f"Verify the following research report for accuracy. Highlight any errors or contradictions. If it is correct, say 'VERIFIED'.\n\nReport:\n{report}"
        verification = await self.hub.llm.generate(prompt)
        
        return {"report": report, "verification": verification, "verified": "VERIFIED" in verification.upper()}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        return output_data.get("verified", False)
