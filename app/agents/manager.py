"""Agent 0: Manager Agent - The Boss who orchestrates all other agents."""
from __future__ import annotations
from app.core.agent import BaseAgent
from app.core.pipeline import AgentState
import logging

log = logging.getLogger("app.agents.manager")

class ManagerAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        topic = input_data.get("topic", "")
        log.info("Manager taking over project %d with topic: %s", project_id, topic)
        
        # The Manager doesn't do the work, he triggers the Orchestrator
        # He coordinates the sequence and returns the final result
        try:
            result = await self.hub.orchestrator.run_pipeline(project_id, {"topic": topic})
            return {"status": "completed", "result": result}
        except Exception as e:
            log.error("Manager failed to coordinate pipeline: %s", e)
            return {"status": "failed", "error": str(e)}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        return output_data.get("status") == "completed"
