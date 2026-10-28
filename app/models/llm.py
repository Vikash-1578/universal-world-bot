"""Text-generation adapter (master prompt §16, §27: replaceable providers, local first, cloud only after opt-in).

Order tried:
  1. Local  — Ollama on this laptop (http://127.0.0.1:11434), if it is running and has a model.
  2. Cloud  — OpenAI-compatible providers from keys.txt (groq, gemini, cerebras, openrouter, mistral, nvidia),
              ONLY when the owner switched Cloud AI on in Settings. Keys rotate; a failing key/provider is skipped.

If nothing is available, `LLMUnavailable` explains what the owner can do (install Ollama or enable Cloud AI) —
the bot never pretends AI text was generated.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import aiohttp

from app.core.errors import HubError, ProviderUnavailable
from app.observability.log import get_logger, redact

log = get_logger(__name__)

CLOUD = {
    # name: (base_url, default_model)
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    "cerebras": ("https://api.cerebras.ai/v1", "llama-3.3-70b"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "meta/llama-3.3-70b-instruct"),
}
OLLAMA = "http://127.0.0.1:11434"


class LLMUnavailable(HubError):
    code = "llm_unavailable"


@dataclass
class Provider:
    name: str
    base: str
    model: str
    keys: list[str] = field(default_factory=list)
    local: bool = False
    cooldown_until: float = 0.0
    next_key: int = 0


class LLM:
    def __init__(self, keys: list[tuple[str, str]], cloud_enabled: Callable[[], bool], *, models: dict[str, str] | None = None,
                 ollama_url: str = OLLAMA, ollama_model: str = "", timeout: float = 90.0,
                 prefer_cloud: Callable[[], bool] = lambda: False) -> None:
        self.cloud_enabled = cloud_enabled
        self.prefer_cloud = prefer_cloud  # owner's choice in Settings: "AI pehle: Cloud"
        self.timeout = timeout
        self.ollama_url = ollama_url.rstrip("/")
        self.ollama_model = ollama_model
        self._ollama_checked = 0.0
        self.local: Provider | None = None
        models = models or {}
        self.cloud: list[Provider] = []
        for name, (base, model) in CLOUD.items():
            ks = [v for k, v in keys if k == name]
            if ks:
                self.cloud.append(Provider(name, base, models.get(name, model), ks))
        self.last_provider = ""

    # ---------------------------------------------------------------- status
    async def detect_local(self, force: bool = False) -> Provider | None:
        if not force and time.time() - self._ollama_checked < 300:
            return self.local
        self._ollama_checked = time.time()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
                async with s.get(f"{self.ollama_url}/api/tags") as r:
                    if r.status != 200:
                        self.local = None
                        return None
                    tags = [m.get("name", "") for m in (await r.json(content_type=None)).get("models", [])]
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
            self.local = None
            return None
        model = self.ollama_model if self.ollama_model in tags else (tags[0] if tags else "")
        self.local = Provider("ollama", f"{self.ollama_url}/v1", model, ["ollama"], local=True) if model else None
        return self.local

    async def status(self) -> dict:
        local = await self.detect_local()
        return {"local": f"ollama:{local.model}" if local else None,
                "cloud": [p.name for p in self.cloud], "cloud_enabled": bool(self.cloud_enabled())}

    async def available(self) -> bool:
        return bool(await self.detect_local()) or (bool(self.cloud) and bool(self.cloud_enabled()))

    # ---------------------------------------------------------------- calls
    async def chat(self, prompt: str, *, system: str = "", max_tokens: int = 2048, temperature: float = 0.7,
                   json_mode: bool = False) -> str:
        local = await self.detect_local()
        locals_ = [local] if local else []
        clouds = [p for p in self.cloud if p.cooldown_until <= time.time()] if self.cloud_enabled() else []
        order: list[Provider] = clouds + locals_ if self.prefer_cloud() else locals_ + clouds
        if not order:
            raise LLMUnavailable(
                "AI likhne ke liye abhi koi model chalu nahi hai.\n"
                "• Laptop par free local AI: ollama.com se Ollama install karo, phir `ollama pull llama3.1:8b`\n"
                "• Ya ⚙️ Settings me Cloud AI ON karo (keys.txt me key chahiye)\n"
                "• Ya apni script khud likh ke bhejo — wo bina AI ke bhi chalegi.")
        errors: list[str] = []
        for p in order:
            for _ in range(max(1, len(p.keys))):
                key = p.keys[p.next_key % len(p.keys)]
                try:
                    text = await self._call(p, key, prompt, system, max_tokens, temperature, json_mode)
                    self.last_provider = f"{p.name}:{p.model}"
                    return text
                except ProviderUnavailable as e:
                    errors.append(f"{p.name}: {e.detail or e.user_message}")
                    p.next_key += 1
                    if "429" in (e.detail or "") or "quota" in (e.detail or "").lower():
                        p.cooldown_until = time.time() + 60
        log.warning("llm_all_failed %s", redact("; ".join(errors))[:400])
        raise ProviderUnavailable("AI abhi jawab nahi de paya (sab providers busy/fail). Thodi der baad try karo.",
                                  detail="; ".join(errors)[:300])

    async def _call(self, p: Provider, key: str, prompt: str, system: str, max_tokens: int, temperature: float,
                    json_mode: bool) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body: dict = {"model": p.model, "messages": msgs, "max_tokens": max_tokens, "temperature": temperature}
        if json_mode and p.name in ("groq", "gemini", "openrouter", "mistral", "ollama"):
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if not p.local:
            headers["Authorization"] = f"Bearer {key}"
        timeout = aiohttp.ClientTimeout(total=self.timeout * (3 if p.local else 1))
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post(f"{p.base}/chat/completions", json=body, headers=headers) as r:
                    raw = await r.text()
                    if r.status != 200:
                        raise ProviderUnavailable("provider error", detail=f"http {r.status} {raw[:160]}")
            j = json.loads(raw)
            text = (j.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
            raise ProviderUnavailable("provider error", detail=type(e).__name__) from e
        text = strip_thinking(text)
        if not text:
            raise ProviderUnavailable("provider error", detail="empty reply")
        return text

    async def chat_json(self, prompt: str, *, system: str = "", max_tokens: int = 3000, attempts: int = 2) -> dict | list:
        last = ""
        for _ in range(attempts):
            text = await self.chat(prompt, system=system, max_tokens=max_tokens, temperature=0.5, json_mode=True)
            data = extract_json(text)
            if data is not None:
                return data
            last = text[:120]
        raise ProviderUnavailable("AI ne sahi format me jawab nahi diya, dobara try karo.", detail=last)


def strip_thinking(text: str) -> str:
    """Reasoning models (Qwen3, DeepSeek-R1) put their private reasoning in <think>...</think>: drop it."""
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I)
    if "<think>" in t.lower():  # unfinished thinking block (cut off) -> keep only what came before it
        t = t[: t.lower().index("<think>")]
    return t.strip()


def extract_json(text: str) -> dict | list | None:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    for cand in (t, t[t.find("{"): t.rfind("}") + 1] if "{" in t else "", t[t.find("["): t.rfind("]") + 1] if "[" in t else ""):
        if not cand:
            continue
        try:
            return json.loads(cand)
        except ValueError:
            continue
    return None
