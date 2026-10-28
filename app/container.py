"""Builds and holds all services (dependency container). Telegram handlers receive `hub` and call services;
they never touch renderers or AI providers directly."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.events import EventBus
from app.core.security import Approvals
from app.observability.audit import Audit
from app.projects.service import ProjectService
from app.scheduler.service import JobService
from app.storage.db import Database


@dataclass
class Hub:
    settings: Settings
    db: Database
    audit: Audit
    approvals: Approvals
    bus: EventBus
    projects: ProjectService
    jobs: JobService
    llm: Any = None
    scripts: Any = None
    storyboards: Any = None
    library: Any = None
    imagegen: Any = None
    tts: Any = None
    extra: dict[str, Any] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    bot: Any = None

    # cloud opt-in (master prompt 3.8/3.9): off until the owner switches it on in Settings
    @property
    def cloud_enabled(self) -> bool:
        return bool(self.db.get_setting("cloud_enabled", False))

    def set_cloud(self, on: bool) -> None:
        self.db.set_setting("cloud_enabled", bool(on))
        self.audit.record("cloud_enable" if on else "cloud_disable")

    async def start(self, bot: Any) -> None:
        self.bot = bot
        for hook in self.extra.get("on_start", []):
            await hook(self)
        await self.jobs.start()
        self.status["scheduler"] = "running"

    async def stop(self) -> None:
        await self.jobs.stop()
        self.status["scheduler"] = "stopped"
        self.db.close()


def build_hub(settings: Settings) -> Hub:
    db = Database(settings.db_path)
    audit = Audit(db)
    bus = EventBus()
    hub = Hub(
        settings=settings,
        db=db,
        audit=audit,
        approvals=Approvals(db, audit),
        bus=bus,
        projects=ProjectService(db, settings.data_dir),
        jobs=JobService(db, bus, settings.data_dir / "work", heavy_slots=settings.max_heavy_workers,
                        light_slots=settings.max_light_workers),
    )
    from app.models.llm import LLM
    from app.scripts.service import ScriptService
    from app.storyboards.service import StoryboardService

    llm_cfg = settings.raw.get("llm", {})
    hub.llm = LLM(settings.keys, lambda: hub.cloud_enabled, models=llm_cfg.get("models"),
                  ollama_url=llm_cfg.get("ollama_url", "http://127.0.0.1:11434"), ollama_model=llm_cfg.get("ollama_model", ""),
                  prefer_cloud=lambda: hub.db.get_setting("ai_order", "local") == "cloud")
    hub.scripts = ScriptService(db, hub.projects, hub.llm)
    hub.storyboards = StoryboardService(db, hub.projects, hub.scripts, hub.llm)
    from app.characters.service import LibraryService
    from app.models.imagegen import CloudflareImages, ComfyUI, ImageRouter

    img_cfg = settings.raw.get("image", {})
    hub.library = LibraryService(db, settings.data_dir)
    comfy = ComfyUI(img_cfg.get("comfyui_url", "http://127.0.0.1:8188"), img_cfg.get("checkpoint", ""), int(img_cfg.get("steps", 24)))
    cf = CloudflareImages(settings.key("cf_account_id", "cloudflare_account_id"), settings.key("cf_api_token", "cloudflare_api_token", "cloudflare"))
    hub.imagegen = ImageRouter(comfy, cf, lambda: hub.cloud_enabled, lambda: hub.db.get_setting("ai_order", "local") == "cloud")
    from app.audio.tts import PiperTTS

    hub.tts = PiperTTS(Path(settings.raw.get("tts", {}).get("voices_dir") or (settings.data_dir / "models" / "piper")))
    from app.pipelines import register_all  # job handlers for each milestone

    from app.telegram.conversations.state import Conversations

    hub.extra["conv"] = Conversations(db)
    register_all(hub)
    return hub
