"""Research agent: topic -> structured key points, each with an honest confidence level.

IMPORTANT: with only a local model the points come from the model's memory, NOT from live sources.
They are labelled `basis: model_memory` and the Fact-Check agent treats them as unverified until a source is attached."""
from __future__ import annotations

from app.agents.base import CONFIDENCE, Agent, AgentResult, Brief, clip

PROMPT = """You are a careful researcher for a faceless YouTube channel about facts, history, geography, science and mysteries.
Topic: {topic}

Return ONLY JSON:
{{"summary": "2 sentences",
  "key_points": [{{"point": "one clear factual statement", "confidence": "high|medium|low", "disputed": false}}],
  "angles": ["3 interesting angles for the video"],
  "avoid": ["claims that are commonly repeated but false or unproven"]}}

Rules: 8-14 key points. Use "high" ONLY for well-established facts. If a claim is a theory, legend or disputed, set disputed=true.
Do NOT invent names, dates, numbers or quotes. If unsure, use "low" or leave the point out."""


def _strings(v: object, n: int) -> list[str]:
    return [clip(a, n) for a in v if clip(a, n)] if isinstance(v, list) else []


def normalise(raw: object) -> dict:
    """Never trust model JSON: force the expected shape and limits."""
    d = raw if isinstance(raw, dict) else {}
    points = []
    for p in d.get("key_points") or []:
        if isinstance(p, str):
            p = {"point": p}
        if not isinstance(p, dict) or not clip(p.get("point"), 400):
            continue
        conf = str(p.get("confidence", "low")).lower()
        points.append({"point": clip(p["point"], 400), "confidence": conf if conf in CONFIDENCE else "low",
                       "disputed": bool(p.get("disputed", False))})
    return {"summary": clip(d.get("summary"), 500), "key_points": points[:16],
            "angles": _strings(d.get("angles"), 160)[:5], "avoid": _strings(d.get("avoid"), 200)[:6],
            "basis": "model_memory"}


class ResearchAgent(Agent):
    name = "research"
    role = "Topic -> key points with confidence"

    async def run(self, brief: Brief) -> AgentResult:
        raw = await self.hub.llm.chat_json(PROMPT.format(topic=brief.topic), max_tokens=2500)
        data = normalise(raw)
        notes = []
        if len(data["key_points"]) < 4:
            notes.append("Bahut kam points mile — topic aur specific likho.")
        res = AgentResult(self.name, ok=len(data["key_points"]) >= 3, data=data, notes=notes, provider=self.hub.llm.last_provider)
        self.save(brief.project_id, res)
        return res
