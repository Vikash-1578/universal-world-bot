"""Builds and holds all services (dependency container). Telegram handlers receive `hub` and call services;
they never touch renderers or AI providers directly."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.core.events import EventBus
from app.core.security import Approvals
from app.observability.audit import Audit
from app.projects.service import ProjectService
from app.scheduler.service import JobService
from app.storage.db import Database

# Agents
from app.agents.manager import ManagerAgent
from app.agents.research import ResearchAgent
from app.agents.accuracy import AccuracyAgent
from app.agents.scripting import ScriptingAgent
from app.agents.virality import ViralityAgent
from app.agents.quality import QualityAgent
from app.agents.voice import VoiceAgent
from app.agents.media import MediaAgent
from app.agents.media_checker import MediaCheckerAgent
from app.agents.editor import EditorAgent
from app.agents.video_checker import VideoCheckerAgent
from app.agents.thumbnail import ThumbnailAgent
from app.agents.seo import SEOAgent
from app.agents.analyser import AnalyserAgent
from app.agents.config import ConfigAgent

# Other Services
from app.audio.tts import TTS
from app.rendering.engine import RenderEngine
from app.core.orchestrator import Orchestrator

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
    
    # Agents
    manager_agent: Any = None
    research_agent: Any = None
    accuracy_agent: Any = None
    scripting_agent: Any = None
    virality_agent: Any = None
    quality_agent: Any = None
    voice_agent: Any = None
    media_agent: Any = None
    media_checker_agent: Any = None
    editor_agent: Any = None
    video_checker_agent: Any = None
    thumbnail_agent: Any = None
    seo_agent: Any = None
    analyser_agent: Any = None
    config_agent: Any = None
    
    # Services
    tts: Any = None
    renderer: Any = None
    orchestrator: Any = None
    
    extra: dict[str, Any] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    bot: Any = None

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
    
    # Services Initialization
    hub.tts = TTS()
    hub.renderer = RenderEngine(settings.data_dir)
    hub.orchestrator = Orchestrator(hub)
    
    # Agent Initialization
    hub.manager_agent = ManagerAgent(hub)
    hub.research_agent = ResearchAgent(hub)
    hub.accuracy_agent = AccuracyAgent(hub)
    hub.scripting_agent = ScriptingAgent(hub)
    hub.virality_agent = ViralityAgent(hub)
    hub.quality_agent = QualityAgent(hub)
    hub.voice_agent = VoiceAgent(hub)
    hub.media_agent = MediaAgent(hub)
    hub.media_checker_agent = MediaCheckerAgent(hub)
    hub.editor_agent = EditorAgent(hub)
    hub.video_checker_agent = VideoCheckerAgent(hub)
    hub.thumbnail_agent = ThumbnailAgent(hub)
    hub.seo_agent = SEOAgent(hub)
    hub.analyser_agent = AnalyserAgent(hub)
    hub.config_agent = ConfigAgent(hub)
    
    from app.pipelines import register_all
    from app.telegram.conversations.state import Conversations

    hub.extra["conv"] = Conversations(db)
    register_all(hub)
    return hub
