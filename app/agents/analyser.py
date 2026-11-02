"""Agent 14: Analyser Agent - Reviews channel performance and suggests topics."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging

log = logging.getLogger("app.agents.analyser")

class AnalyserAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        log.info("Analyzing channel performance for future topics...")
        
        # Simulation: In a real setup, we'd call YT Analytics API
        analysis = "Based on current trends, 'Unsolved Mysteries of Ancient India' has 40% higher potential."
        
        return {"analysis": analysis, "suggestion": "Ancient India Mysteries"}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        return "analysis" in output_data
