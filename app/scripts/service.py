"""Script Studio service (master prompt §9): versions, approval, AI drafting, never silently replacing an approved script.

Rules
* Every change creates a NEW version (draft). Old versions are kept.
* Only one version can be "approved". Approving a new one marks the previous approved one "superseded".
* An approved version is never edited in place.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.core.errors import Conflict, InvalidInput, NotFound
from app.scripts import parser

if TYPE_CHECKING:
    from app.models.llm import LLM
    from app.projects.service import ProjectService
    from app.storage.db import Database

MAX_SCRIPT = 60_000
LANG = {"hindi": "Hindi (Devanagari script)", "english": "English", "hinglish": "Hinglish (Hindi in Latin letters)"}

WRITE_PROMPT = """You are a researcher and scriptwriter for a faceless YouTube channel about amazing facts, history, geography,
science and mysteries. Write an ORIGINAL narration script.
Topic: {idea}
Language for the narration: {lang}. Audience: {audience}. Tone: {tone}. Target length: about {seconds} seconds.

Content rules:
- Start with a strong hook in the very first line (a surprising fact or question). End with a clear closing line.
- Only state facts you are confident are true. Do NOT invent names, dates, numbers or quotes. If something is disputed or unproven,
  say so plainly ("historians disagree", "this is a theory"). Leave out anything you are unsure about.
- Mysteries: separate what is known, what is claimed, and what is proven. No fear-mongering and no graphic detail.
- Never repeat the same sentence or phrase. Use simple, natural, correct words. 5-9 scenes, each with a clear point.

FORMAT RULES (very important — a computer reads this):
- The markers Title:, [Scene N: ...] and Narrator: are ALWAYS written in English letters exactly like this, even for a Hindi script.
- After the scene marker, put a short visual hint for the editor (what footage or map to show), then the narration lines.
- Visual hints go on their own line in brackets: (show: old map of the Atlantic)
- No markdown, no bold, no notes, nothing before Title: and nothing after the last line.

EXAMPLE OF THE FORMAT (content is only an example):
Title: Bermuda Triangle ka asli raaz
[Scene 1: Hook]
(show: stormy ocean, ship on horizon)
Narrator: Kya ek poora jahaz bina nishaan ke gayab ho sakta hai?
[Scene 2: Kahani kahan se shuru hui]
(show: map of the Atlantic with the triangle)
Narrator: ...

Now write the full script:
"""

STORY_PROMPT = """Turn these notes into a narration SCRIPT for a faceless facts / history / mystery YouTube video.
Keep the facts as given; do not add facts you are not sure about. Do not invent names, dates or numbers.
Language for the narration: {lang}. Audience: {audience}. 5-9 scenes. Do not repeat lines.

FORMAT RULES (a computer reads this):
- Title:, [Scene N: topic] and Narrator: are ALWAYS in English letters, even for a Hindi script.
- Visual hints on their own line in brackets: (show: ...)
- No markdown, nothing before Title: and nothing after the last line.

NOTES:
{story}
"""

REVISE_PROMPT = """Revise this narration script. Keep the same format: Title:, [Scene N: ...], (show: ...) visual hints,
Narrator: (always in English letters). Do not repeat lines. Use simple correct words.
Do not add facts you are not sure about. Change ONLY what the instruction asks.
Instruction: {instruction}

SCRIPT:
{script}
"""


class ScriptService:
    def __init__(self, db: "Database", projects: "ProjectService", llm: "LLM | None" = None) -> None:
        self.db = db
        self.projects = projects
        self.llm = llm

    # ---------------------------------------------------------------- versions
    def create_version(self, project_id: int, content: str, *, language: str | None = None, note: str = "") -> dict:
        p = self.projects.get_project(project_id)
        content = (content or "").strip()
        if len(content) < 10:
            raise InvalidInput("Script bahut chhoti hai.")
        if len(content) > MAX_SCRIPT:
            raise InvalidInput(f"Script {MAX_SCRIPT} akshar se lambi hai.")
        ps = parser.parse(content)
        if not ps.scenes:
            raise InvalidInput("Script me koi line samajh nahi aayi.")
        row = self.db.one("SELECT COALESCE(MAX(version_number), 0) AS n FROM scripts WHERE project_id = ?", (project_id,))
        n = int(row["n"]) + 1
        sid = self.db.insert("scripts", {"project_id": project_id, "version_number": n,
                                         "language": language or p["settings"].get("language", "hindi"),
                                         "content": content, "approval_status": "draft", "created_at": time.time()})
        if p["status"] == "draft":
            self.projects.update_project(project_id, {"status": "scripting"})
        self.projects.write_manifest(project_id)
        return self.get(sid)

    def get(self, script_id: int) -> dict:
        row = self.db.one("SELECT * FROM scripts WHERE id = ?", (int(script_id),))
        if not row:
            raise NotFound("Script version nahi mila.")
        return row

    def versions(self, project_id: int) -> list[dict]:
        return self.db.all("SELECT id, version_number, approval_status, language, created_at, length(content) AS chars "
                           "FROM scripts WHERE project_id = ? ORDER BY version_number DESC", (project_id,))

    def latest(self, project_id: int) -> dict | None:
        return self.db.one("SELECT * FROM scripts WHERE project_id = ? ORDER BY version_number DESC LIMIT 1", (project_id,))

    def approved(self, project_id: int) -> dict | None:
        return self.db.one("SELECT * FROM scripts WHERE project_id = ? AND approval_status = 'approved'", (project_id,))

    def approve(self, script_id: int) -> dict:
        s = self.get(script_id)
        if s["approval_status"] == "approved":
            return s

        def tx(db: "Database") -> None:
            db.execute("UPDATE scripts SET approval_status = 'superseded' WHERE project_id = ? AND approval_status = 'approved'",
                       (s["project_id"],))
            db.execute("UPDATE scripts SET approval_status = 'approved' WHERE id = ?", (script_id,))

        self.db.tx(tx)
        self.projects.save_version(s["project_id"], f"Script v{s['version_number']} approved")
        return self.get(script_id)

    def reject(self, script_id: int) -> dict:
        s = self.get(script_id)
        if s["approval_status"] == "approved":
            raise Conflict("Approved script ko reject nahi karte — nayi version banao.")
        self.db.update("scripts", script_id, {"approval_status": "rejected"})
        return self.get(script_id)

    def parsed(self, script_id: int) -> parser.ParsedScript:
        return parser.parse(self.get(script_id)["content"])

    # ---------------------------------------------------------------- AI
    async def write_with_ai(self, project_id: int, idea: str) -> dict:
        if self.llm is None:
            from app.models.llm import LLMUnavailable

            raise LLMUnavailable("AI engine set nahi hai.")
        idea = " ".join((idea or "").split())[:800]
        if len(idea) < 5:
            raise InvalidInput("Idea thoda aur likho.")
        s = self.projects.get_project(project_id)["settings"]
        prompt = WRITE_PROMPT.format(idea=idea, lang=LANG.get(s.get("language", "hinglish"), "Hinglish (Hindi in Latin letters)"),
                                     audience=s.get("audience", "general"), tone=s.get("tone", "curious"),
                                     seconds=s.get("target_seconds", 60))
        text = await self.llm.chat(prompt, max_tokens=3000)
        return self.create_version(project_id, _clean(text), note=f"AI ({self.llm.last_provider})")

    async def story_to_script(self, project_id: int, story: str) -> dict:
        """Pasted / uploaded notes -> narration script format with AI."""
        if self.llm is None:
            from app.models.llm import LLMUnavailable

            raise LLMUnavailable("AI engine set nahi hai.")
        story = (story or "").strip()[:12000]
        s = self.projects.get_project(project_id)["settings"]
        text = await self.llm.chat(STORY_PROMPT.format(story=story, lang=LANG.get(s.get("language", "hinglish"), "Hinglish (Hindi in Latin letters)"),
                                                       audience=s.get("audience", "general")), max_tokens=3500)
        return self.create_version(project_id, _clean(text), note=f"Notes se script, AI ({self.llm.last_provider})")

    async def revise_with_ai(self, script_id: int, instruction: str) -> dict:
        if self.llm is None:
            from app.models.llm import LLMUnavailable

            raise LLMUnavailable("AI engine set nahi hai.")
        s = self.get(script_id)
        text = await self.llm.chat(REVISE_PROMPT.format(instruction=instruction[:500], script=s["content"]), max_tokens=3500)
        return self.create_version(s["project_id"], _clean(text), language=s["language"])


def _clean(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t.split("\n", 1)[1] if "\n" in t else t
    return t.strip()
