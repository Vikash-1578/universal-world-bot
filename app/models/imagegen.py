"""Local image generation through ComfyUI (master prompt §11: AI-generated visual references when an approved
model is available). ComfyUI runs on the owner's laptop (default http://127.0.0.1:8188); nothing is uploaded.

The bot sends a minimal text-to-image graph (checkpoint -> prompt -> sampler -> image). Which checkpoint to use
is chosen in config.toml ([image] checkpoint = "...") or the first one ComfyUI reports. If ComfyUI is not
running, `ImageGenUnavailable` explains how to set it up — the bot never fakes an image.
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid

import aiohttp

from app.core.errors import HubError, ProviderUnavailable

COMFY = "http://127.0.0.1:8188"
NEGATIVE = "text, watermark, logo, blurry, deformed, extra limbs, cropped, frame, border"
CHARACTER_SUFFIX = ", full body, standing, centered, plain solid bright green background, no shadow, clean outlines"
BACKGROUND_SUFFIX = ", wide establishing shot, empty scene with no characters, 16:9"


class ImageGenUnavailable(HubError):
    code = "imagegen_unavailable"


class ComfyUI:
    def __init__(self, url: str = COMFY, checkpoint: str = "", steps: int = 24, cfg: float = 6.5, timeout: float = 600) -> None:
        self.url = url.rstrip("/")
        self.checkpoint = checkpoint
        self.steps = steps
        self.cfg = cfg
        self.timeout = timeout

    async def _get(self, path: str, **params) -> aiohttp.ClientResponse | dict:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(f"{self.url}{path}", params=params) as r:
                if r.status != 200:
                    raise ProviderUnavailable("ComfyUI error", detail=f"http {r.status}")
                return await r.json(content_type=None)

    async def checkpoints(self) -> list[str]:
        try:
            info = await self._get("/object_info/CheckpointLoaderSimple")
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ProviderUnavailable):
            return []
        try:
            return list(info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0])
        except (KeyError, IndexError, TypeError):
            return []

    async def available(self) -> bool:
        return bool(await self.checkpoints())

    def workflow(self, prompt: str, ckpt: str, width: int, height: int, seed: int) -> dict:
        return {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["1", 1]}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
                                                       "seed": seed, "steps": self.steps, "cfg": self.cfg, "sampler_name": "euler",
                                                       "scheduler": "normal", "denoise": 1.0}},
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "uwb"}},
        }

    async def generate(self, prompt: str, *, width: int = 832, height: int = 1216, seed: int | None = None,
                       progress=None) -> bytes:
        cks = await self.checkpoints()
        if not cks:
            raise ImageGenUnavailable(
                "Image banane wala local AI (ComfyUI) nahi mila.\n"
                "• ComfyUI install karke chalao (docs/model-compatibility.md me steps), aur ek SDXL checkpoint daalo\n"
                "• Tab tak character ki photo/drawing khud upload karo — wo bhi poori tarah chalega")
        ckpt = self.checkpoint if self.checkpoint in cks else cks[0]
        seed = seed if seed is not None else random.randint(1, 2**31 - 1)
        body = {"prompt": self.workflow(prompt, ckpt, width, height, seed), "client_id": uuid.uuid4().hex}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
                async with s.post(f"{self.url}/prompt", json=body) as r:
                    j = await r.json(content_type=None)
                    if r.status != 200 or "prompt_id" not in j:
                        raise ProviderUnavailable("ComfyUI ne kaam nahi liya.", detail=str(j)[:200])
                pid = j["prompt_id"]
                end = time.time() + self.timeout
                while time.time() < end:
                    await asyncio.sleep(2)
                    if progress:
                        await progress()
                    async with s.get(f"{self.url}/history/{pid}") as r:
                        h = await r.json(content_type=None)
                    if pid in h:
                        out = h[pid].get("outputs", {}).get("7", {}).get("images", [])
                        if not out:
                            raise ProviderUnavailable("ComfyUI ne image nahi di.", detail=str(h[pid].get("status"))[:200])
                        img = out[0]
                        async with s.get(f"{self.url}/view", params={"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                                                     "type": img.get("type", "output")}) as r:
                            if r.status != 200:
                                raise ProviderUnavailable("ComfyUI image download fail.", detail=f"http {r.status}")
                            return await r.read()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            raise ProviderUnavailable("ComfyUI se baat nahi ho payi.", detail=type(e).__name__) from e
        raise ProviderUnavailable("ComfyUI ne time par image nahi banayi.", detail="timeout")
