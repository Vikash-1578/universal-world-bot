"""Agent 13: SEO Agent - Optimizes Title, Tags, and Description."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging

log = logging.getLogger("app.agents.seo")

class SEOAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        topic = input_data.get("topic", "Unknown")
        log.info("Optimizing SEO for project %d...", project_id)
        
        prompt = (
            f"Create high-CTR SEO metadata for a YouTube video about {topic}.\n"
            f"Provide:\n1. Three viral Title options (curiosity-driven)\n"
            f"2. A search-optimized Description (first 2 lines must be hooks)\n"
            f"3. 15 high-volume Tags separated by commas."
        )
        seo_data = await self.hub.llm.generate(prompt)
        
        return {"seo_metadata": seo_data, "topic": topic}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        return len(output_data.get("seo_metadata", "")) > 100
