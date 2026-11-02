"""Agent 1: Research Agent - Gathers facts from the web."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging
from pathlib import Path

log = logging.getLogger("app.agents.research")

class ResearchAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        topic = input_data.get("topic", "Unknown Topic")
        log.info("Researching topic: %s", topic)
        
        # Simulating web research via LLM (In real world, we'd use a search tool)
        # For now, we use the hub's LLM to generate a research report
        prompt = f"Research the following topic for a YouTube video: {topic}. Provide detailed facts, dates, and key points."
        report = await self.hub.llm.generate(prompt)
        
        return {"report": report, "source": "ai_research"}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        # Basic verification: check if report is long enough and has content
        report = output_data.get("report", "")
        return len(report) > 100
