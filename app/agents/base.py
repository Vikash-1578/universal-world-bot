"""Common pieces: Brief (what the owner asked), AgentResult (what an agent returns), Agent base class."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.container import Hub

CONFIDENCE = ("high", "medium", "low")


@dataclass
class Brief:
    project_id: int
    topic: str
    language: str = "hinglish"
    audience: str = "general"
    tone: str = "curious"
    target_seconds: int = 480

    @classmethod
    def from_project(cls, hub: "Hub", project_id: int, topic: str) -> "Brief":
        s = hub.projects.get_project(project_id)["settings"]
        return cls(project_id, " ".join(topic.split())[:800], s.get("language", "hinglish"), s.get("audience", "general"),
                   s.get("tone", "curious"), int(s.get("target_seconds", 480)))


@dataclass
class AgentResult:
    agent: str
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    provider: str = ""

    def to_dict(self) -> dict:
        return {"agent": self.agent, "ok": self.ok, "data": self.data, "notes": self.notes, "provider": self.provider}


class Agent:
    name = "agent"
    role = ""

    def __init__(self, hub: "Hub") -> None:
        self.hub = hub

    def save(self, project_id: int, result: AgentResult) -> None:
        """Keep every agent's output on disk (project/agents/<name>.json) so the owner can inspect it."""
        folder = self.hub.projects.folder(project_id, "agents")
        payload = {**result.to_dict(), "saved_at": time.time()}
        (folder / f"{self.name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clip(text: Any, n: int) -> str:
    return " ".join(str(text or "").split())[:n]
