"""Agent 9: Media Checker - Ensures visuals match the mood and quality."""
from __future__ import annotations
from app.core.agent import BaseAgent
import logging
from pathlib import Path

log = logging.getLogger("app.agents.media_checker")

class MediaCheckerAgent(BaseAgent):
    async def execute(self, project_id: int, input_data: dict) -> dict:
        media_map = input_data.get("media_map", {})
        log.info("Checking media quality for project %d...", project_id)
        
        all_valid = True
        for sid, path in media_map.items():
            if not Path(path).exists() or Path(path).stat().st_size < 1024:
                log.warning("Asset for scene %s is missing or too small", sid)
                all_valid = False
        
        return {"media_map": media_map, "all_valid": all_valid, "script": input_data.get("script", "")}

    async def verify(self, project_id: int, output_data: dict) -> bool:
        return output_data.get("all_valid", False)
