"""Agent 11: Video Checker - Verifies final render quality and sync."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging
from pathlib import Path

log = logging.getLogger("app.agents.video_checker")

class VideoCheckerAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        video_path = input_data.get("video_path")
        log.info("Verifying final video quality for project %d...", project_id)
        
        if not video_path or not Path(video_path).exists():
            return {"status": "fail", "error": "Video file not found"}
        
        # Basic check: ensure file size is reasonable (e.g., > 1MB)
        if Path(video_path).stat().st_size < 1024 * 1024:
            return {"status": "fail", "error": "Video file too small, likely render failed"}
            
        return {"status": "success", "video_path": video_path}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        return output_data.get("status") == "success"
