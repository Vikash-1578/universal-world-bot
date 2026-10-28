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
NEGATIVE = "text, watermark, logo, blurry, deformed, extra limbs, cropped, frame, border, ground, grass, floor, shadow, platform"
CHARACTER_SUFFIX = (", single character, full body from head to feet, standing, centered, on a plain flat solid white background, "
                    "nothing else in the picture, no ground, no grass, no floor, no shadow, no white outline around the body")
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


# ---------------------------------------------------------------- cloud backup (opt-in)
CF_BASE = "https://api.cloudflare.com/client/v4/accounts"
CF_MODELS = ("@cf/black-forest-labs/flux-1-schnell", "@cf/leonardo/lucid-origin", "@cf/leonardo/phoenix-1.0",
             "@cf/bytedance/stable-diffusion-xl-lightning", "@cf/stabilityai/stable-diffusion-xl-base-1.0")


class CloudflareImages:
    """Cloudflare Workers AI text-to-image (free daily quota). Used ONLY when the owner switched Cloud AI on.
    The prompt text goes to Cloudflare; no local files are uploaded."""

    def __init__(self, account: str, token: str, base: str = CF_BASE, models: tuple[str, ...] = CF_MODELS, timeout: float = 120) -> None:
        self.account, self.token = account.strip(), token.strip()
        self.base = base.rstrip("/")
        self.models = list(models)
        self.good: str | None = None
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.account and self.token)

    async def _post(self, s: aiohttp.ClientSession, model: str, payload: dict) -> bytes:
        import base64

        async with s.post(f"{self.base}/{self.account}/ai/run/{model}", json=payload,
                          headers={"Authorization": f"Bearer {self.token}"}) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if r.status != 200:
                raise ProviderUnavailable("Cloudflare image error", detail=f"http {r.status} {(await r.text())[:200]}")
            if ctype.startswith("image/"):
                return await r.read()
            j = await r.json(content_type=None)
        res = j.get("result") if isinstance(j, dict) else None
        b64 = res.get("image") if isinstance(res, dict) else res if isinstance(res, str) else None
        if not b64:
            raise ProviderUnavailable("Cloudflare ne image nahi di.", detail=str(j)[:200])
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[-1]
        return base64.b64decode(b64)

    async def generate(self, prompt: str, *, width: int = 832, height: int = 1216, seed: int | None = None, progress=None) -> bytes:
        order = ([self.good] if self.good else []) + [m for m in self.models if m != self.good]
        errors: list[str] = []
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as s:
                for model in order:
                    if progress:
                        await progress()
                    base: dict = {"prompt": prompt[:2000]}
                    if "flux-1-schnell" in model:
                        base["steps"] = 6
                    else:
                        base.update({"width": width, "height": height})
                    for payload in ([dict(base, seed=seed)] if seed is not None else []) + [base]:
                        try:
                            data = await self._post(s, model, payload)
                            self.good = model
                            return data
                        except ProviderUnavailable as e:
                            errors.append(f"{model.rsplit('/', 1)[-1]}: {e.detail}"[:160])
                            if any(f"http {c}" in (e.detail or "") for c in (401, 403, 429)):
                                raise ProviderUnavailable("Cloudflare key / daily limit problem.", detail="; ".join(errors)) from e
                            if "http 400" not in (e.detail or ""):
                                break
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            raise ProviderUnavailable("Cloudflare se baat nahi ho payi.", detail=type(e).__name__) from e
        raise ProviderUnavailable("Cloudflare ne image nahi banayi.", detail="; ".join(errors)[-300:])


class ImageRouter:
    """Local ComfyUI first (default) or Cloudflare first when the owner chose "AI pehle: Cloud".
    Cloudflare is used only while Cloud AI is ON."""

    def __init__(self, comfy: ComfyUI, cloud: CloudflareImages | None, cloud_enabled, prefer_cloud=lambda: False) -> None:
        self.comfy = comfy
        self.cloud = cloud if cloud and cloud.configured else None
        self.cloud_enabled = cloud_enabled
        self.prefer_cloud = prefer_cloud
        self.last_provider = ""

    @property
    def url(self) -> str:  # kept for tests / config display
        return self.comfy.url

    @url.setter
    def url(self, v: str) -> None:
        self.comfy.url = v.rstrip("/")

    async def sources(self) -> dict[str, bool]:
        return {"comfyui": await self.comfy.available(), "cloudflare": bool(self.cloud and self.cloud_enabled())}

    async def available(self) -> bool:
        src = await self.sources()
        return src["comfyui"] or src["cloudflare"]

    async def generate(self, prompt: str, *, width: int = 832, height: int = 1216, seed: int | None = None, progress=None) -> bytes:
        src = await self.sources()
        order = [n for n in (("cloudflare", "comfyui") if self.prefer_cloud() else ("comfyui", "cloudflare")) if src[n]]
        if not order:
            raise ImageGenUnavailable(
                "Image AI abhi chalu nahi hai.\n"
                "• Free cloud: keys.txt me CF_ACCOUNT_ID + CF_API_TOKEN (Cloudflare) daalo aur ⚙️ Settings me Cloud AI ON karo\n"
                "• Ya laptop par ComfyUI install karo (docs: model-compatibility)\n"
                "• Ya 🖼 Image bhejo se apni drawing/photo do")
        last: Exception | None = None
        for name in order:
            try:
                eng = self.comfy if name == "comfyui" else self.cloud
                data = await eng.generate(prompt, width=width, height=height, seed=seed, progress=progress)  # type: ignore[union-attr]
                self.last_provider = name
                return data
            except (ProviderUnavailable, ImageGenUnavailable) as e:
                last = e
        raise last if last else ImageGenUnavailable("Image nahi bani.")
