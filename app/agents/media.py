"""Agent 8: Media Agent - Sources real stock footage and AI visuals."""
from __future__ import annotations
from app.core.agent import BaseAgent
import httpx
import logging
from pathlib import Path
import re

log = logging.getLogger("app.agents.media")

class MediaAgent(BaseAgent):
    def __init__(self, hub):
        super().__init__(hub)
        self.pixabay_key = "58372853-281f817032d287076fb401b50"
        self.coverr_key = "517485fe28bfc0f5d228c118ad1ff808"

    async def execute(self, project_id: int, input_data: dict) -> dict:
        script = input_data.get("script", "")
        log.info("Sourcing media for project %d...", project_id)
        
        export_dir = self.hub.projects.folder(project_id, "assets", "media")
        export_dir.mkdir(parents=True, exist_ok=True)
        
        scenes = re.split(r"\[Scene \d+.*?\]", script)
        scenes = [s.strip() for s in scenes if s.strip()]
        
        media_map = {}
        
        async with httpx.AsyncClient() as client:
            for idx, text in enumerate(scenes):
                # Simple prompt extraction: use first 5 words of scene
                prompt = " ".join(text.split()[:5])
                scene_id = idx + 1
                
                # Try Pixabay first
                pix_url = f"https://pixabay.com/api/videos/?key={self.pixabay_key}&q={prompt}&per_page=3"
                pix_res = await client.get(pix_url)
                pix_data = pix_res.json()
                
                asset_path = None
                if pix_data.get("hits"):
                    # Use the first video/image
                    asset_url = pix_data["hits"][0].get("videos", {}).get("medium", {}).get("url") or pix_data["hits"][0].get("previewURL")
                    if asset_url:
                        asset_path = await self._download(client, asset_url, export_dir / f"scene_{scene_id}.mp4")
                
                # Fallback to AI if no stock found
                if not asset_path:
                    log.info("No stock found for scene %d, using AI...", scene_id)
                    asset_path = await self.hub.free_gen.generate(text[:100], export_dir / f"scene_{scene_id}.jpg")
                
                media_map[scene_id] = str(asset_path)
                
        return {"media_map": media_map, "script": script}

    async def _download(self, client, url, path):
        try:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            path.write_bytes(resp.content)
            return path
        except Exception as e:
            log.error("Download failed: %s", e)
            return None

    async def verify(self, project_id: int, output_data: dict) -> bool:
        media = output_data.get("media_map", {})
        if not media: return False
        return True
