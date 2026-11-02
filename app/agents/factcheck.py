"""Fact-Check agent.

1. `verify_points` asks the model to re-judge each research point (a second, independent pass) and keeps only what survives.
2. `script_flags` is DETERMINISTIC: any number/year in the narration that is not in the verified points is flagged.
This is a safety net, not proof. Without live sources nothing is called "verified" — only "kept" or "dropped"."""
from __future__ import annotations

import re

from app.agents.base import Agent, AgentResult, Brief
from app.scripts import parser

PROMPT = """You are a strict fact-checker. For each numbered claim say whether it is well established.
Topic: {topic}

CLAIMS:
{claims}

Return ONLY JSON: {{"verdicts": [{{"n": 1, "verdict": "supported|uncertain|likely_wrong", "reason": "max 12 words"}}]}}
Use "supported" only for well-established facts. Legends, theories and disputed claims are "uncertain"."""

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUM.findall(text or "")}


def script_flags(script_text: str, allowed_text: str) -> list[dict]:
    """Narration sentences that contain a number not backed by the verified points."""
    allowed = numbers_in(allowed_text)
    out = []
    for sc in parser.parse(script_text).scenes:
        for ln in sc.lines:
            if ln.kind == "action":  # (show: ...) visual hints are not claims
                continue
            extra = sorted(n for n in numbers_in(ln.text) if n not in allowed)
            if extra:
                out.append({"scene": sc.number, "text": ln.text[:160], "numbers": extra})
    return out


class FactCheckAgent(Agent):
    name = "factcheck"
    role = "Keep only claims that survive a second check; flag unbacked numbers"

    async def verify_points(self, brief: Brief, research: dict) -> AgentResult:
        points = research.get("key_points", [])
        claims = "\n".join(f"{i}. {p['point']}" for i, p in enumerate(points, 1))
        verdicts: dict[int, dict] = {}
        notes: list[str] = []
        try:
            raw = await self.hub.llm.chat_json(PROMPT.format(topic=brief.topic, claims=claims), max_tokens=2000)
            for v in (raw.get("verdicts") if isinstance(raw, dict) else None) or []:
                if isinstance(v, dict) and str(v.get("n", "")).isdigit():
                    verdicts[int(v["n"])] = {"verdict": str(v.get("verdict", "uncertain")).lower(), "reason": str(v.get("reason", ""))[:120]}
        except Exception as e:  # noqa: BLE001 - checker failure must never silently pass claims
            notes.append(f"Second check fail hua ({type(e).__name__}); sirf high-confidence points rakhe.")
        kept, dropped = [], []
        for i, p in enumerate(points, 1):
            v = verdicts.get(i, {}).get("verdict", "unchecked")
            reason = verdicts.get(i, {}).get("reason", "")
            ok = v != "likely_wrong" and p["confidence"] != "low" and (v == "supported" or p["confidence"] == "high")
            if v == "uncertain":
                p = {**p, "disputed": True}  # script must say "isn't proven"
            (kept if ok else dropped).append({**p, "check": v, "reason": reason})
        res = AgentResult(self.name, ok=len(kept) >= 3, data={"kept": kept, "dropped": dropped},
                          notes=notes + ([f"{len(dropped)} claim hataye gaye."] if dropped else []), provider=self.hub.llm.last_provider)
        self.save(brief.project_id, res)
        return res
