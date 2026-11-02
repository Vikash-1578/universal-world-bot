"""Free image generation service using Pollinations.ai."""
from __future__ import annotations

import httpx
import logging
from pathlib import Path

log = logging.getLogger("app.models.free_images")

class FreeImages:
    def __init__(self, width: int = 1024, height: int = 1024):
        self.width = width
        self.height = height
        self.base_url = "https://image.pollinations.ai/prompt/"

    async def generate(self, prompt: str, output_path: Path) -> Path:
        """Generates an image from a prompt and saves it to output_path."""
        # Clean prompt for URL
        safe_prompt = prompt.replace(" ", "%20")
        url = f"{self.base_url}{safe_prompt}?width={self.width}&height={self.height}&nologo=true"
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
                output_path.write_bytes(resp.content)
                return output_path
        except Exception as e:
            log.error("Free image generation failed: %s", e)
            raise e
