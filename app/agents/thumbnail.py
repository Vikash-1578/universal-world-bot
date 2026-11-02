"""Agent 12: Thumbnail Agent - Generates high-CTR AI thumbnails."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging
from pathlib import Path

log = logging.getLogger("app.agents.thumbnail")

class ThumbnailAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        topic = input_data.get("topic", "Mystery")
        log.info("Generating viral thumbnail for %s...", topic)
        
        # Create a high-impact prompt for AI
        prompt = f"High-contrast, cinematic, hyper-realistic YouTube thumbnail for a video about {topic}. Mystery vibe, 8k, dramatic lighting, focal point center, no text."
        
        export_dir = self.hub.projects.folder(project_id, "exports")
        thumb_path = export_dir / "thumbnail.jpg"
        
        await self.hub.free_gen.generate(prompt, thumb_path)
        
        return {"thumbnail_path": str(thumb_path), "topic": topic}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        path = output_data.get("thumbnail_path")
        return path is not None and Path(path).exists()
