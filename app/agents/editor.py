"""Agent 10: Editor Agent - Manages the pro rendering process."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging
from pathlib import Path

log = logging.getLogger("app.agents.editor")

class EditorAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        log.info("Professional editing in progress for project %d...", project_id)
        
        try:
            # Use the Pro Render Engine
            output_path = await self.hub.renderer.render_project(self.hub, project_id)
            return {"video_path": str(output_path), "status": "rendered"}
        except Exception as e:
            log.error("Editing failed: %s", e)
            raise e

    async def verify(self, project_id: int, output_data: dict) -> bool:
        path = output_data.get("video_path")
        return path is not None and Path(path).exists()
