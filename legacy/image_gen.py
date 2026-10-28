"""
Text -> image, photo edit and text -> video (Pollinations).

Needs a `pollinations:KEY` line in keys.txt / AI_KEYS. Without a key the feature
stays off and the bot behaves exactly as before.

Everything is best-effort: prompt rewriting failures never block an image, and
edit/video fall back across models. Video models are all credit ("pollen") based,
so /video reports clearly when the account has no credit.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from urllib.parse import quote

import aiohttp

from app.utils.logging import get_logger

log = get_logger(__name__)

HOST = "https://gen.pollinations.ai"
DEFAULT_BASE = HOST + "/image"
MAX_PROMPT_CHARS = 500
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_VIDEO_BYTES = 45 * 1024 * 1024  # Telegram bots can send up to 50 MB
DEFAULT_MODEL = "flux"  # free + healthy; override with IMAGE_MODEL env
DEFAULT_EDIT_MODELS = ("black-forest-labs/flux.1-kontext-pro", "openai/gpt-image-1-mini")
DEFAULT_VIDEO_MODEL = "wan-fast"  # cheapest video model; override with VIDEO_MODEL env
CF_BASE = "https://api.cloudflare.com/client/v4/accounts"
CF_MODEL = "@cf/black-forest-labs/flux-1-schnell"  # free tier: 10k neurons/day ~ 170 images
CF_MODELS = (CF_MODEL, "@cf/leonardo/lucid-origin", "@cf/leonardo/phoenix-1.0",
             "@cf/bytedance/stable-diffusion-xl-lightning", "@cf/stabilityai/stable-diffusion-xl-base-1.0",
             "@cf/lykon/dreamshaper-8-lcm")
FREE_URL = "https://image.pollinations.ai/prompt"  # no key, slow (1 picture / ~15 s)
NO_CREDIT_PAUSE = 30 * 60  # Pollinations said "no credit" -> skip it for 30 min
NO_TEXT_SUFFIX = ", no text, no letters, no words, no watermark, no captions, no logo"

STYLES = {
    "realistic": "ultra realistic photograph, natural lighting, sharp focus, highly detailed",
    "cartoon": "cute colorful cartoon illustration, bold clean outlines, kid friendly",
    "anime": "anime style illustration, vibrant colors, detailed, studio quality",
    "3d": "3D render, Pixar style, soft lighting, smooth shading",
    "painting": "oil painting, rich brush strokes, artistic, museum quality",
    "kids": "bright kids cartoon, simple shapes, rounded friendly characters, soft colours, children's TV show style",
    "webtoon": "webtoon comic style, clean line art, soft cel shading, pastel colours",
    "comic": "comic book illustration, bold ink outlines, halftone shading, dynamic colours",
    "flat": "flat vector art, simple geometric shapes, no gradients, minimal and clean",
    "clay": "claymation style, plasticine models, soft studio lighting, handmade look",
    "watercolor": "soft watercolour illustration, gentle washes of colour, storybook feel",
    "pixel": "pixel art, 16-bit retro game style, crisp pixels",
    "indian": "Indian 2D cartoon animation style, warm colours, village and town details",
}
# name -> (width, height). Multiples of 16 and >= 768 so every model accepts them.
SIZES = {
    "square": (1024, 1024),
    "portrait": (768, 1344),
    "landscape": (1344, 768),
}
SIZE_ALIASES = {
    "1:1": "square", "sq": "square",
    "9:16": "portrait", "reel": "portrait", "story": "portrait", "vertical": "portrait",
    "16:9": "landscape", "thumb": "landscape", "thumbnail": "landscape", "wide": "landscape",
    "horizontal": "landscape",
}
MODEL_ALIASES = {
    "flux": "flux",
    "zimage": "z-image",
    "z-image": "z-image",
    "klein": "klein",
    "mai": "microsoft/mai-image-2.6-flash",
    "gpt": "gpt-image",
    "dream": "dreamshaper",
}

REWRITE_INSTRUCTION = (
    "Convert the user's request (Hinglish/Hindi/English) into ONE detailed English prompt "
    "for a text-to-image model. Translate the subject literally and correctly "
    "(e.g. 'billi' = cat, 'sher' = lion). Describe subject, setting, lighting, style. "
    "If the request has 'Modification requested:', keep the same subject, pose and scene and ONLY apply "
    "that change (e.g. 'enhance' = sharper, more detailed, better lighting, same subject). "
    "Do NOT make a poster, cover or book/movie title. Output ONLY the prompt, max 60 words.\n\n"
    "Request: "
)
EDIT_REWRITE_INSTRUCTION = (
    "Rewrite this photo-edit instruction (Hinglish/Hindi/English) as ONE clear English sentence for an "
    "image editing model. Keep the meaning exactly. Output ONLY the sentence.\n\nInstruction: "
)

_WANTS_TEXT_RE = re.compile(
    r"\b(text|likh|likha|likho|write|written|naam|name|quote|caption|title|slogan|lettering|font)\b", re.I
)


def wants_text_in_image(prompt: str) -> bool:
    return bool(_WANTS_TEXT_RE.search(prompt or ""))


def resolve_size(name: str | None) -> str | None:
    n = (name or "").strip().lower()
    if n in SIZES:
        return n
    return SIZE_ALIASES.get(n)


def resolve_model(name: str | None) -> str | None:
    n = (name or "").strip().lower()
    return MODEL_ALIASES.get(n)


class ImageGenError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None) -> None:
        super().__init__(msg)
        self.status = status


class _RetryKey(ImageGenError):
    pass


_NOUNS = (
    r"image|images|photo|photos|picture|pictures|pic|pics|tasveer|tasvir|"
    r"logo|poster|wallpaper|illustration|painting|sketch|artwork|banner|thumbnail|dp"
)
_VERBS = (
    r"bana|banao|bnao|banado|banadena|banana|bana\s*do|bana\s*de|banao|generate|"
    r"create|draw|make|design|paint|render|imagine"
)
_NOUN_RE = re.compile(rf"\b(?:{_NOUNS})\b", re.I)
_VERB_RE = re.compile(rf"\b(?:{_VERBS})\b", re.I)
# These usually mean "write code / explain", not "give me a picture".
_NOT_IMAGE_RE = re.compile(
    r"\b(code|function|script|program|python|javascript|html|css|api|class|"
    r"library|bot|app|website|sql|regex|explain|samjha|kaise|how)\b",
    re.I,
)


def image_prompt_from_text(text: str) -> str | None:
    """Return the prompt if `text` looks like an image request, else None."""
    t = (text or "").strip()
    if not t or len(t) > 600 or t.startswith("/"):
        return None
    if not (_NOUN_RE.search(t) and _VERB_RE.search(t)):
        return None
    if _NOT_IMAGE_RE.search(t):
        return None
    return t[:MAX_PROMPT_CHARS]


_VIDEO_NOUN_RE = re.compile(r"\b(video|videos|clip|reel|animation)\b", re.I)
_NOT_VIDEO_RE = re.compile(
    r"\b(script|idea|ideas|title|caption|description|download|edit|editing|app|software|tool|code|"
    r"explain|samjha|kaise|how|youtube|channel|upload|compress|convert|kya hai|what is)\b",
    re.I,
)


def video_prompt_from_text(text: str) -> str | None:
    """Return the prompt if `text` looks like a 'make me a video' request, else None."""
    t = (text or "").strip()
    if not t or len(t) > 400 or t.startswith("/"):
        return None
    if not (_VIDEO_NOUN_RE.search(t) and _VERB_RE.search(t)):
        return None
    if _NOT_VIDEO_RE.search(t):
        return None
    return t[:MAX_PROMPT_CHARS]


_HEX32 = re.compile(r"\b[0-9a-f]{32}\b", re.I)


def cf_from_text(text: str) -> tuple[str | None, str | None]:
    """Find Cloudflare account id + token in .env / keys.txt text, whatever way they were written:
    CF_ACCOUNT_ID=.. / CF_API_TOKEN=..  or  cloudflare_account:.. / cloudflare:TOKEN  or  cloudflare:ACCOUNT:TOKEN"""
    acc = tok = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_ ]+?)\s*[=:]\s*(.+)$", line)
        if not m:
            continue
        name = m.group(1).strip().lower().replace(" ", "_")
        val = m.group(2).strip().strip("\"'")
        if not val or "cf" not in name and "cloudflare" not in name:
            continue
        if "account" in name or name in ("cf_id", "cloudflare_id"):
            acc = val.split()[0]
        elif name in ("cloudflare", "cf", "workers_ai", "cf_ai"):
            parts = [p for p in re.split(r"[:/\s]+", val) if p]
            if len(parts) >= 2 and _HEX32.fullmatch(parts[0]):
                acc, tok = parts[0], parts[1]
            elif parts:
                tok = parts[0]
        elif "token" in name or "key" in name:
            tok = val.split()[0]
    return acc, tok


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


class ImageGenerator:
    def __init__(
        self,
        keys: list[str],
        *,
        base_url: str = DEFAULT_BASE,
        host: str | None = None,
        timeout: float = 90.0,
        concurrency: int = 2,
        model: str = DEFAULT_MODEL,
        enhancer=None,
        edit_models: tuple[str, ...] | list[str] | None = None,
        video_model: str = DEFAULT_VIDEO_MODEL,
        video_timeout: float = 300.0,
        cf_account: str | None = None,
        cf_token: str | None = None,
        cf_base: str = CF_BASE,
        cf_models: list[str] | tuple[str, ...] | None = None,
        free_url: str | None = None,
        free_gap: float = 16.0,
    ) -> None:
        self._keys = [k for k in keys if k]
        self._base = base_url.rstrip("/")
        # host used for /v1, /video and /upload (tests point it at a fake server)
        self._host = (host or (self._base.rsplit("/image", 1)[0] if self._base.endswith("/image") else self._base)).rstrip("/")
        self._timeout = timeout
        self._video_timeout = video_timeout
        self._sem = asyncio.Semaphore(concurrency)
        self._next = 0
        self._model = (model or "").strip()
        self._enhancer = enhancer  # async (str) -> str, optional
        self._edit_models = tuple(edit_models or DEFAULT_EDIT_MODELS)
        self._video_model = video_model
        # backups when Pollinations has no credit / fails
        self._cf = (cf_account.strip(), cf_token.strip()) if cf_account and cf_token else None
        self._cf_base = cf_base.rstrip("/")
        self._cf_list = list(cf_models or CF_MODELS)
        self._cf_good: str | None = None
        self._free_url = (free_url or "").rstrip("/") or None
        self._free_gap = free_gap
        self._free_lock = asyncio.Lock()
        self._free_next = 0.0
        self._poll_off_until = 0.0
        self._free_off_until = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._keys) or self._cf is not None

    @property
    def providers(self) -> list[str]:
        out = ["pollinations"] if self._keys else []
        if self._cf:
            out.append("cloudflare")
        if self._free_url and out:
            out.append("free")
        return out

    @property
    def default_model(self) -> str:
        return self._model

    # ---------- helpers ----------
    async def _rewrite(self, instruction: str, text: str, max_len: int = 900) -> str | None:
        if self._enhancer is None:
            return None
        try:
            better = (await self._enhancer(instruction + text) or "").strip().strip('"').strip()
        except Exception as e:  # rewrite is best-effort
            log.warning("image_prompt_rewrite_failed err=%s", type(e).__name__)
            return None
        return better if 5 <= len(better) <= max_len else None

    async def english_prompt(self, text: str) -> str | None:
        """Hinglish/Hindi idea -> detailed English image prompt (None if no LLM / failed)."""
        return await self._rewrite(REWRITE_INSTRUCTION, (text or "").strip()[:MAX_PROMPT_CHARS])

    def _key_order(self) -> list[str]:
        n = len(self._keys)
        return [self._keys[(self._next + i) % n] for i in range(n)]

    async def _with_keys(self, fn):
        """Run fn(key) over the keys; bad/limited key -> next key."""
        if not self._keys:
            raise ImageGenError("no pollinations key configured")
        last: ImageGenError = ImageGenError("unknown")
        async with self._sem:
            for key in self._key_order():
                try:
                    return await fn(key)
                except _RetryKey as e:
                    last = e
            self._next = (self._next + 1) % len(self._keys)
        raise ImageGenError(str(last), getattr(last, "status", None))

    @staticmethod
    async def _read_body(r: aiohttp.ClientResponse, cap: int) -> bytes:
        buf = bytearray()
        async for chunk in r.content.iter_chunked(64 * 1024):
            buf.extend(chunk)
            if len(buf) > cap:
                raise ImageGenError("file too large")
        data = bytes(buf)
        if r.content_length is not None and len(data) != r.content_length:
            raise ImageGenError("incomplete download")
        if not data:
            raise ImageGenError("empty response")
        return data

    @staticmethod
    def _check_status(status: int, body_hint: str = "") -> None:
        if status in (401, 402, 403, 429):
            raise _RetryKey(f"http {status}", status)
        if status != 200:
            raise ImageGenError(f"http {status} {body_hint}".strip(), status)

    @staticmethod
    async def _error_hint(r: aiohttp.ClientResponse) -> str:
        try:
            j = await r.json(content_type=None)
            err = j.get("error") if isinstance(j, dict) else None
            if isinstance(err, dict):
                return f"{err.get('code', '')}: {str(err.get('message', ''))[:100]}"
        except Exception:
            pass
        return ""

    # ---------- text -> image ----------
    async def generate(
        self,
        prompt: str,
        seed: int | None = None,
        info: dict | None = None,
        *,
        model: str | None = None,
        size: str | None = None,
        style: str | None = None,
        enhance: bool = True,
        no_text: bool | None = None,
    ) -> bytes:
        prompt = (prompt or "").strip()[:MAX_PROMPT_CHARS]  # raw user text
        if not prompt:
            raise ImageGenError("empty prompt")
        if not self.enabled:
            raise ImageGenError("no pollinations key configured")
        keep_text = wants_text_in_image(prompt) if no_text is None else not no_text
        if enhance:
            better = await self._rewrite(REWRITE_INSTRUCTION, prompt)
            if better:
                prompt = better
        if info is not None:
            info["prompt"] = prompt  # final English prompt (no style / suffix)
        if style in STYLES:
            prompt = f"{prompt}, {STYLES[style]}"
        if not keep_text:
            prompt = prompt[: 1400 - len(NO_TEXT_SUFFIX)] + NO_TEXT_SUFFIX
        wh = SIZES.get(size or "")
        use_model = (model or self._model).strip()

        async def run(m: str):
            return await self._with_keys(lambda k: self._fetch(prompt, k, seed, m, wh))

        async def pollinations() -> bytes:
            try:
                return await run(use_model)
            except ImageGenError as e:
                if use_model and use_model != DEFAULT_MODEL and (e.status is None or e.status in (400, 404, 422, 500, 502, 503)):
                    log.warning("image_model_fallback model=%s err=%s", use_model, e)
                    if info is not None:
                        info["model_fallback"] = use_model
                    return await run(DEFAULT_MODEL)
                raise

        steps = []
        if self._keys and time.time() >= self._poll_off_until:
            steps.append(("pollinations", pollinations))
        if self._cf:
            steps.append(("cloudflare", lambda: self._cloudflare(prompt, seed)))
        if self._free_url and (self._keys or self._cf) and time.time() >= self._free_off_until:
            steps.append(("free", lambda: self._free(prompt, seed, wh)))
        errors: list[str] = []
        first: ImageGenError | None = None
        for name, fn in steps:
            try:
                data = await fn()
                if info is not None:
                    info["provider"] = name
                return data
            except ImageGenError as e:
                first = first or e
                errors.append(f"{name}: {e}")
                log.warning("image_provider_failed provider=%s err=%s", name, e)
                if e.status == 402 or str(e).startswith("http 402"):
                    if name == "pollinations":
                        self._poll_off_until = time.time() + NO_CREDIT_PAUSE
                    elif name == "free":
                        self._free_off_until = time.time() + NO_CREDIT_PAUSE
                if "content_blocked" in str(e) or (e.status == 400 and name == "pollinations" and len(steps) == 1):
                    break
        if first is None:
            raise ImageGenError("pollinations credit khatam (30 min baad phir try hoga)", 402)
        raise ImageGenError("; ".join(errors)[:400], first.status)

    async def _cf_post(self, s: aiohttp.ClientSession, model: str, payload: dict) -> bytes:
        acc, token = self._cf  # type: ignore[misc]
        async with s.post(f"{self._cf_base}/{acc}/ai/run/{model}", json=payload,
                          headers={"Authorization": f"Bearer {token}"}) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if r.status != 200:
                body = (await r.text())[:300]
                raise ImageGenError(f"http {r.status} {body}".strip(), r.status)
            if ctype.startswith("image/"):
                return await self._read_body(r, MAX_IMAGE_BYTES)
            j = await r.json(content_type=None)
        res = (j or {}).get("result") if isinstance(j, dict) else None
        b64 = res.get("image") if isinstance(res, dict) else res if isinstance(res, str) else None
        if not b64:
            raise ImageGenError("cloudflare returned no image")
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[-1]
        data = base64.b64decode(b64)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ImageGenError("bad image size")
        return data

    async def _cf_models(self, s: aiohttp.ClientSession) -> list[str]:
        """Ask Cloudflare which text-to-image models this account can use."""
        acc, token = self._cf  # type: ignore[misc]
        try:
            async with s.get(f"{self._cf_base}/{acc}/ai/models/search", params={"task": "Text-to-Image"},
                             headers={"Authorization": f"Bearer {token}"}) as r:
                if r.status != 200:
                    return []
                j = await r.json(content_type=None)
            return [m["name"] for m in (j.get("result") or []) if isinstance(m, dict) and m.get("name")]
        except Exception:  # noqa: BLE001
            return []

    async def _cloudflare(self, prompt: str, seed: int | None) -> bytes:
        prompt = prompt[:2000]
        order = [getattr(self, "_cf_good", None)] + [m for m in self._cf_list]
        tried: set[str] = set()
        errors: list[str] = []
        timeout = aiohttp.ClientTimeout(total=max(self._timeout, 120.0))
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                discovered = False
                while True:
                    model = next((m for m in order if m and m not in tried), None)
                    if model is None:
                        if discovered:
                            break
                        discovered = True
                        order += await self._cf_models(s)
                        continue
                    tried.add(model)
                    base: dict = {"prompt": prompt}
                    if "flux-1-schnell" in model:
                        base["steps"] = 4
                    tries = [dict(base, seed=int(seed) % 2_000_000_000 + 1), base] if seed is not None else [base]
                    for payload in tries:
                        try:
                            data = await self._cf_post(s, model, payload)
                            self._cf_good = model
                            return data
                        except ImageGenError as e:
                            errors.append(f"{model.rsplit('/', 1)[-1]}: {e}"[:160])
                            log.warning("cloudflare_model_failed model=%s err=%s", model, str(e)[:200])
                            if e.status in (401, 403, 429):  # bad token / daily limit: other models won't help
                                raise ImageGenError("; ".join(errors)[-300:], e.status)
                            if e.status != 400:
                                break
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            raise ImageGenError(type(e).__name__) from e
        raise ImageGenError("; ".join(errors)[-300:] or "cloudflare: no image model", 400)

    async def _free(self, prompt: str, seed: int | None, wh) -> bytes:
        """Keyless Pollinations: one picture at a time with a pause between them."""
        params = {"nologo": "true", "model": "flux"}
        if seed is not None:
            params["seed"] = str(seed)
        if wh:
            params["width"], params["height"] = str(wh[0]), str(wh[1])
        url = f"{self._free_url}/{quote(prompt[:900], safe='')}"
        async with self._free_lock:
            wait = self._free_next - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                timeout = aiohttp.ClientTimeout(total=max(self._timeout, 120.0))
                async with aiohttp.ClientSession(timeout=timeout) as s:
                    async with s.get(url, params=params) as r:
                        if r.status != 200:
                            raise ImageGenError(f"http {r.status}", r.status)
                        if not (r.headers.get("Content-Type") or "").lower().startswith("image/"):
                            raise ImageGenError("not an image")
                        return await self._read_body(r, MAX_IMAGE_BYTES)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise ImageGenError(type(e).__name__) from e
            finally:
                self._free_next = time.monotonic() + self._free_gap

    async def _fetch(self, prompt: str, key: str, seed: int | None = None, model: str = "", wh=None) -> bytes:
        params = {"key": key, "nologo": "true"}
        if model:
            params["model"] = model
        if seed is not None:
            params["seed"] = str(seed)
        if wh:
            params["width"], params["height"] = str(wh[0]), str(wh[1])
        url = f"{self._base}/{quote(prompt, safe='')}"
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(url, params=params) as r:
                    ctype = (r.headers.get("Content-Type") or "").lower()
                    self._check_status(r.status, await self._error_hint(r) if r.status != 200 else "")
                    if not ctype.startswith("image/"):
                        raise ImageGenError(f"not an image ({ctype or 'no type'})")
                    return await self._read_body(r, MAX_IMAGE_BYTES)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise ImageGenError(type(e).__name__) from e

    # ---------- photo edit ----------
    async def edit(
        self,
        image: bytes,
        instruction: str,
        mime: str = "image/jpeg",
        *,
        seed: int | None = None,
        translate: bool = True,
    ) -> bytes:
        instruction = (instruction or "").strip()[:800]
        if not instruction:
            raise ImageGenError("empty instruction")
        if not image or len(image) > MAX_IMAGE_BYTES:
            raise ImageGenError("bad source image")
        if translate:
            better = await self._rewrite(EDIT_REWRITE_INSTRUCTION, instruction, 600)
            if better:
                instruction = better
        instruction += ". Change only what is asked, keep everything else the same."
        uri = _data_uri(image, mime)
        last: ImageGenError = ImageGenError("edit failed")
        for m in self._edit_models:
            payload = {
                "prompt": instruction,
                "image": [{"image_url": uri}],
                "model": m,
                "n": 1,
                "response_format": "b64_json",
            }
            if seed is not None:
                payload["seed"] = seed
            try:
                return await self._with_keys(lambda k, p=payload: self._post_edit(p, k))
            except ImageGenError as e:
                last = e
                log.warning("image_edit_model_failed model=%s err=%s", m, e)
                if "content_blocked" in str(e):
                    break
        raise last

    async def _post_edit(self, payload: dict, key: str) -> bytes:
        timeout = aiohttp.ClientTimeout(total=max(self._timeout, 120.0))
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post(f"{self._host}/v1/images/edits", data=json.dumps(payload), headers=headers) as r:
                    if r.status != 200:
                        self._check_status(r.status, await self._error_hint(r))
                    j = await r.json(content_type=None)
                item = (j.get("data") or [{}])[0] if isinstance(j, dict) else {}
                if item.get("b64_json"):
                    data = base64.b64decode(item["b64_json"])
                elif item.get("url"):
                    async with s.get(item["url"]) as r2:
                        if r2.status != 200:
                            raise ImageGenError(f"result http {r2.status}", r2.status)
                        data = await self._read_body(r2, MAX_IMAGE_BYTES)
                else:
                    raise ImageGenError("edit returned no image")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            raise ImageGenError(type(e).__name__) from e
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ImageGenError("bad image size")
        return data

    # ---------- text/photo -> video ----------
    async def upload(self, data: bytes, mime: str = "image/jpeg", filename: str = "frame.jpg") -> str:
        """Upload a start frame; returns its URL (needed for image -> video)."""

        async def run(key: str) -> str:
            form = aiohttp.FormData()
            form.add_field("file", data, filename=filename, content_type=mime)
            timeout = aiohttp.ClientTimeout(total=60)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as s:
                    async with s.post(f"{self._host}/upload", data=form, headers={"Authorization": f"Bearer {key}"}) as r:
                        if r.status not in (200, 201):
                            self._check_status(r.status, await self._error_hint(r))
                        j = await r.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                raise ImageGenError(type(e).__name__) from e
            url = j.get("url") if isinstance(j, dict) else None
            if not url and isinstance(j, dict) and j.get("id"):
                url = f"https://media.pollinations.ai/{j['id']}"
            if not url:
                raise ImageGenError("upload returned no url")
            return url

        return await self._with_keys(run)

    async def video(
        self,
        prompt: str,
        image: bytes | None = None,
        *,
        mime: str = "image/jpeg",
        model: str | None = None,
        duration: int = 5,
        aspect: str | None = None,
    ) -> bytes:
        prompt = (prompt or "").strip()[:MAX_PROMPT_CHARS]
        if not prompt:
            raise ImageGenError("empty prompt")
        if not self._keys:
            raise ImageGenError("no pollinations key configured")
        better = await self._rewrite(REWRITE_INSTRUCTION, prompt)
        if better:
            prompt = better
        frame_url = await self.upload(image, mime) if image else None
        use_model = model or self._video_model

        async def run(key: str) -> bytes:
            params = {"key": key, "model": use_model, "duration": str(duration)}
            if aspect:
                params["aspectRatio"] = aspect
            if frame_url:
                params["image"] = frame_url
            timeout = aiohttp.ClientTimeout(total=self._video_timeout)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as s:
                    async with s.get(f"{self._host}/video/{quote(prompt[:700], safe='')}", params=params) as r:
                        ctype = (r.headers.get("Content-Type") or "").lower()
                        self._check_status(r.status, await self._error_hint(r) if r.status != 200 else "")
                        if not ctype.startswith("video/"):
                            raise ImageGenError(f"not a video ({ctype or 'no type'})")
                        return await self._read_body(r, MAX_VIDEO_BYTES)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise ImageGenError(type(e).__name__) from e

        return await self._with_keys(run)
