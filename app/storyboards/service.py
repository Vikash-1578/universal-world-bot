"""Storyboard Studio (master prompt §10): approved script -> structured scenes -> owner approval.

* The draft is built deterministically from the approved script (works with no AI).
* If an AI model is available, the AI Director (director.py) suggests camera, emotion, action, lighting, props,
  sound cues, transitions and continuity notes. Its output is only a *suggestion* in the draft.
* Any edit / reorder / regenerate after approval puts the storyboard back to "needs approval".
* An approved storyboard is never overwritten silently: regenerating it needs `replace_approved=True`.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from app.core.errors import Conflict, InvalidInput, NotFound
from app.scripts import parser
from app.storage.db import dumps, loads

if TYPE_CHECKING:
    from app.models.llm import LLM
    from app.projects.service import ProjectService
    from app.scripts.service import ScriptService
    from app.storage.db import Database

SHOTS = ("wide", "medium", "close-up", "over-shoulder", "two-shot", "top-down")
MOVES = ("static", "slow zoom in", "slow zoom out", "pan left", "pan right", "follow")
TRANSITIONS = ("cut", "fade", "dissolve", "wipe")
EDITABLE = {"description", "environment_ref", "duration_seconds", "shot", "movement", "lighting", "props", "sfx",
            "transition", "mood", "notes", "style"}


def _lighting(heading: str) -> str:
    h = heading.lower()
    for words, light in ((("raat", "night", "रात"), "night, moonlight"), (("subah", "morning", "सुबह"), "soft morning light"),
                         (("shaam", "evening", "शाम", "sunset"), "warm sunset"), (("dopahar", "noon", "दोपहर"), "bright daylight")):
        if any(w in h for w in words):
            return light
    return "bright daylight"


def default_scene(ps: parser.ParsedScene, idx: int, total: int, prev_env: str) -> dict[str, Any]:
    n_dialogue = sum(1 for ln in ps.lines if ln.kind == "dialogue")
    if idx == 0:
        shot, move = "wide", "slow zoom in"
    elif n_dialogue >= 2 and len(ps.characters) >= 2:
        shot, move = "two-shot", "static"
    elif n_dialogue:
        shot, move = ("medium", "static") if idx % 2 else ("close-up", "slow zoom in")
    else:
        shot, move = "wide", "pan right"
    env = ps.heading or prev_env or "same place"
    return {
        "description": " ".join(ln.text for ln in ps.lines if ln.kind == "action")[:300]
        or (ps.lines[0].text[:200] if ps.lines else ""),
        "environment_ref": env,
        "duration_seconds": ps.seconds,
        "camera": {"shot": shot, "movement": move, "lighting": _lighting(env), "props": [], "sfx": [],
                   "transition": "fade" if idx in (0, total - 1) else "cut", "mood": "", "notes": "", "style": "",
                   "emotions": {ln.speaker: ln.direction for ln in ps.lines if ln.kind == "dialogue" and ln.direction},
                   "source": "rules"},
        "dialogue": [{"kind": ln.kind, "speaker": ln.speaker, "text": ln.text, "direction": ln.direction} for ln in ps.lines],
        "characters": ps.characters,
    }


class StoryboardService:
    def __init__(self, db: "Database", projects: "ProjectService", scripts: "ScriptService", llm: "LLM | None" = None) -> None:
        self.db = db
        self.projects = projects
        self.scripts = scripts
        self.llm = llm

    # ---------------------------------------------------------------- state
    def state(self, project_id: int) -> dict:
        return self.db.get_setting(f"storyboard:{int(project_id)}", {"status": "none"})

    def _set_state(self, project_id: int, **kw: Any) -> dict:
        st = {**self.state(project_id), **kw, "updated_at": time.time()}
        self.db.set_setting(f"storyboard:{int(project_id)}", st)
        return st

    def scenes(self, project_id: int) -> list[dict]:
        rows = self.db.all("SELECT * FROM scenes WHERE project_id = ? ORDER BY scene_number", (int(project_id),))
        for r in rows:
            r["dialogue"] = loads(r.pop("dialogue_json"), [])
            r["characters"] = loads(r.pop("character_refs_json"), [])
            r["camera"] = loads(r.pop("camera_json"), {})
        return rows

    def scene(self, project_id: int, scene_id: int) -> dict:
        for s in self.scenes(project_id):
            if s["id"] == int(scene_id):
                return s
        raise NotFound("Scene nahi mila.")

    def _changed(self, project_id: int) -> None:
        st = self.state(project_id)
        self.db.execute("UPDATE scenes SET approval_status = 'draft' WHERE project_id = ?", (project_id,))
        if st.get("status") == "approved":
            self._set_state(project_id, status="changed", note="Approve ke baad badlaav hua - dobara approval chahiye")
        elif st.get("status") not in ("draft", "changed"):
            self._set_state(project_id, status="draft")
        self.projects.write_manifest(project_id)

    # ---------------------------------------------------------------- draft
    async def generate_draft(self, project_id: int, *, use_ai: bool = True, replace_approved: bool = False) -> dict:
        script = self.scripts.approved(project_id)
        if not script:
            raise Conflict("Pehle Script Studio me script approve karo, phir storyboard banega.")
        if self.state(project_id).get("status") == "approved" and not replace_approved:
            raise Conflict("Storyboard pehle se approved hai. Naya banane ke liye 'replace' confirm karo.")
        ps = parser.parse(script["content"])
        if not ps.scenes:
            raise InvalidInput("Script me scenes nahi mile.")
        drafts, prev_env = [], ""
        for i, sc in enumerate(ps.scenes):
            d = default_scene(sc, i, len(ps.scenes), prev_env)
            prev_env = d["environment_ref"]
            drafts.append(d)
        ai_note = "rules only"
        if use_ai and self.llm is not None and await self.llm.available():
            from app.storyboards.director import enrich

            try:
                drafts = await enrich(self.llm, drafts, self.projects.get_project(project_id)["settings"], ps.title)
                ai_note = f"AI Director ({self.llm.last_provider})"
            except Exception as e:  # noqa: BLE001 — AI suggestions are optional; the rules-based draft stays
                ai_note = f"AI Director fail ({getattr(e, 'user_message', type(e).__name__)}), rules wala draft"

        def tx(db: "Database") -> None:
            db.execute("DELETE FROM scenes WHERE project_id = ?", (project_id,))
            for i, d in enumerate(drafts, 1):
                db.insert("scenes", {"project_id": project_id, "script_id": script["id"], "scene_number": i,
                                     "description": d["description"], "dialogue_json": dumps(d["dialogue"]),
                                     "character_refs_json": dumps(d["characters"]), "environment_ref": d["environment_ref"],
                                     "camera_json": dumps(d["camera"]), "duration_seconds": d["duration_seconds"],
                                     "approval_status": "draft"})

        self.db.tx(tx)
        self._set_state(project_id, status="draft", script_id=script["id"], script_version=script["version_number"],
                        title=ps.title, source=ai_note, note="")
        self.projects.update_project(project_id, {"status": "storyboard"})
        return self.state(project_id)

    # ---------------------------------------------------------------- edits
    def update_scene(self, project_id: int, scene_id: int, changes: dict) -> dict:
        s = self.scene(project_id, scene_id)
        bad = set(changes) - EDITABLE
        if bad:
            raise InvalidInput(f"Ye cheez edit nahi hoti: {', '.join(sorted(bad))}")
        cam = dict(s["camera"])
        vals: dict[str, Any] = {}
        for k, v in changes.items():
            if k in ("description", "environment_ref"):
                vals[k] = str(v)[:500]
            elif k == "duration_seconds":
                d = float(v)
                if not 1 <= d <= 600:
                    raise InvalidInput("Scene 1 se 600 second ke beech ho.")
                vals[k] = d
            elif k == "shot" and v not in SHOTS:
                raise InvalidInput(f"Shot in me se ho: {', '.join(SHOTS)}")
            elif k == "transition" and v not in TRANSITIONS:
                raise InvalidInput(f"Transition in me se ho: {', '.join(TRANSITIONS)}")
            else:
                cam[k] = v if not isinstance(v, str) else v[:300]
        cam["source"] = "owner"
        vals["camera_json"] = dumps(cam)
        self.db.update("scenes", s["id"], vals)
        self._changed(project_id)
        return self.scene(project_id, scene_id)

    def reorder_scene(self, project_id: int, scene_id: int, new_position: int) -> list[dict]:
        rows = self.scenes(project_id)
        ids = [r["id"] for r in rows]
        if int(scene_id) not in ids:
            raise NotFound("Scene nahi mila.")
        new_position = max(1, min(len(ids), int(new_position)))
        ids.remove(int(scene_id))
        ids.insert(new_position - 1, int(scene_id))

        def tx(db: "Database") -> None:
            for i, sid in enumerate(ids, 1):
                db.execute("UPDATE scenes SET scene_number = ? WHERE id = ?", (i, sid))

        self.db.tx(tx)
        self._changed(project_id)
        return self.scenes(project_id)

    async def regenerate_scene(self, project_id: int, scene_id: int, instruction: str = "") -> dict:
        s = self.scene(project_id, scene_id)
        if self.llm is None or not await self.llm.available():
            from app.models.llm import LLMUnavailable

            raise LLMUnavailable("Scene dobara banane ke liye AI chahiye (Ollama ya Cloud AI). Tab tak ✏️ Edit se khud badlo.")
        from app.storyboards.director import enrich

        draft = {"description": s["description"], "environment_ref": s["environment_ref"], "duration_seconds": s["duration_seconds"],
                 "camera": s["camera"], "dialogue": s["dialogue"], "characters": s["characters"]}
        new = (await enrich(self.llm, [draft], self.projects.get_project(project_id)["settings"], "", instruction))[0]
        self.db.update("scenes", s["id"], {"description": new["description"], "environment_ref": new["environment_ref"],
                                           "camera_json": dumps(new["camera"])})
        self._changed(project_id)
        return self.scene(project_id, scene_id)

    # ---------------------------------------------------------------- approval
    def approve(self, project_id: int) -> dict:
        rows = self.scenes(project_id)
        if not rows:
            raise Conflict("Pehle storyboard draft banao.")
        script = self.scripts.approved(project_id)
        st = self.state(project_id)
        if not script or st.get("script_id") != script["id"]:
            raise Conflict("Script badal gayi hai. Naya storyboard draft banao, phir approve karo.")
        self.db.execute("UPDATE scenes SET approval_status = 'approved' WHERE project_id = ?", (project_id,))
        v = self.projects.save_version(project_id, f"Storyboard approved ({len(rows)} scenes)")
        self.projects.update_project(project_id, {"status": "production"})
        return self._set_state(project_id, status="approved", approved_version=v["version_number"], approved_at=time.time(), note="")

    def reject(self, project_id: int, reason: str = "") -> dict:
        if not self.scenes(project_id):
            raise Conflict("Storyboard hai hi nahi.")
        self.db.execute("UPDATE scenes SET approval_status = 'rejected' WHERE project_id = ?", (project_id,))
        return self._set_state(project_id, status="rejected", note=reason[:200])

    def is_approved(self, project_id: int) -> bool:
        st = self.state(project_id)
        script = self.scripts.approved(project_id)
        return st.get("status") == "approved" and script is not None and st.get("script_id") == script["id"]

    # ---------------------------------------------------------------- display
    def scene_text(self, s: dict, total: int) -> str:
        c = s["camera"]
        lines = [f"🎞 Scene {s['scene_number']}/{total} · ~{s['duration_seconds']:.0f}s · {s['approval_status']}",
                 f"📍 {s['environment_ref'] or '-'}",
                 f"🎥 {c.get('shot', '-')} · {c.get('movement', '-')} · 💡 {c.get('lighting', '-')} · ↪ {c.get('transition', '-')}"]
        if s["characters"]:
            lines.append("👥 " + ", ".join(s["characters"]))
        if c.get("mood"):
            lines.append(f"🎭 Mood: {c['mood']}")
        if s["description"]:
            lines.append(f"📝 {s['description'][:300]}")
        for d in s["dialogue"][:8]:
            who = d["speaker"] or ("🎙" if d["kind"] == "narration" else "🎬")
            em = f" ({d['direction']})" if d.get("direction") else ""
            lines.append(f"  {who}{em}: {d['text'][:160]}")
        if len(s["dialogue"]) > 8:
            lines.append(f"  … +{len(s['dialogue']) - 8} lines")
        for key, icon in (("props", "🧸"), ("sfx", "🔊")):
            if c.get(key):
                lines.append(f"{icon} {', '.join(map(str, c[key]))[:200]}")
        if c.get("notes"):
            lines.append(f"🔗 Continuity: {c['notes'][:200]}")
        lines.append(f"(suggestion source: {c.get('source', '-')})")
        return "\n".join(lines)
