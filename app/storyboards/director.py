"""AI Director (master prompt §13C): suggests shots, pacing, blocking, emotion, lighting, props, sound cues and
continuity for each scene. Output is validated and merged into the draft; it never changes dialogue text and
never approves anything."""
from __future__ import annotations

import json
from typing import Any

from app.models.llm import LLM
from app.storyboards.service import MOVES, SHOTS, TRANSITIONS

PROMPT = """You are an animation director. For each scene below suggest staging for a {style} cartoon ({audience} audience).
Return ONLY JSON: {{"scenes": [{{"n": 1, "environment": "...", "description": "what we see, 1-2 sentences",
"shot": one of {shots}, "movement": one of {moves}, "lighting": "...", "mood": "...", "props": ["..."],
"sfx": ["..."], "transition": one of {transitions}, "emotions": {{"Character": "emotion"}}, "notes": "continuity note"}}]}}
Keep environments consistent between scenes in the same place. Do NOT rewrite dialogue.{extra}
Story title: {title}
SCENES:
{scenes}
"""


def _pick(v: Any, allowed: tuple[str, ...], default: str) -> str:
    v = str(v or "").strip().lower()
    return v if v in allowed else default


async def enrich(llm: LLM, drafts: list[dict], settings: dict, title: str, instruction: str = "") -> list[dict]:
    brief = []
    for i, d in enumerate(drafts, 1):
        lines = "; ".join(f"{x['speaker'] or x['kind']}: {x['text'][:120]}" for x in d["dialogue"][:10])
        brief.append(f"{i}. place: {d['environment_ref']} | {lines}")
    extra = f"\nOwner's instruction: {instruction[:300]}" if instruction else ""
    data = await llm.chat_json(PROMPT.format(style=settings.get("style", "kids cartoon"), audience=settings.get("audience", "kids"),
                                             shots=json.dumps(SHOTS), moves=json.dumps(MOVES), transitions=json.dumps(TRANSITIONS),
                                             extra=extra, title=title or "-", scenes="\n".join(brief)))
    items = data.get("scenes") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("director returned no scenes")
    out = []
    for i, d in enumerate(drafts):
        sug = next((x for x in items if isinstance(x, dict) and int(x.get("n", -1) or -1) == i + 1), None)
        if sug is None and i < len(items) and isinstance(items[i], dict):
            sug = items[i]
        if not sug:
            out.append(d)
            continue
        cam = dict(d["camera"])
        cam.update({
            "shot": _pick(sug.get("shot"), SHOTS, cam.get("shot", "medium")),
            "movement": _pick(sug.get("movement"), MOVES, cam.get("movement", "static")),
            "transition": _pick(sug.get("transition"), TRANSITIONS, cam.get("transition", "cut")),
            "lighting": str(sug.get("lighting") or cam.get("lighting", ""))[:120],
            "mood": str(sug.get("mood") or "")[:80],
            "props": [str(p)[:40] for p in (sug.get("props") or [])][:8],
            "sfx": [str(p)[:40] for p in (sug.get("sfx") or [])][:8],
            "notes": str(sug.get("notes") or "")[:200],
            "emotions": {**cam.get("emotions", {}), **{str(k)[:30]: str(v)[:30] for k, v in (sug.get("emotions") or {}).items()}},
            "source": "ai-director",
        })
        out.append({**d, "environment_ref": str(sug.get("environment") or d["environment_ref"])[:200],
                    "description": str(sug.get("description") or d["description"])[:400], "camera": cam})
    return out
