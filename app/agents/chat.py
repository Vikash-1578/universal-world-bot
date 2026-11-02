"""Manager chat: the ONE place the owner talks to. Plain Hinglish text in, plain reply out.

Fast offline rules first (status, team, approve, new video, show script); the local LLM is used only to understand
anything else. Risky actions (approve, start a job) are confirmed with "haan/nahi" before they run. The Manager never
approves a script on its own — only after the owner says haan."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.agents.team import team_text
from app.scheduler.service import ACTIVE

if TYPE_CHECKING:
    from app.container import Hub

YES_RE = re.compile(r"^(ha+n?|haan ?ji|yes|y|ok|okay|theek|thik|kar do|kardo|karo|done)\b")
FILLER = {"topic", "video", "naya", "naaya", "nayi", "ek", "chahiye", "banao", "bana", "do", "ka", "ki", "ke", "hai"}
GREET = {"hello", "hi", "hii", "hey", "namaste", "hlo", "helo", "hello bhai", "hi bhai"}
ACK = {"ok", "okay", "acha", "accha", "thik hai", "theek hai", "hmm", "thanks", "shukriya"}
NO = {"nahi", "nahin", "no", "n", "mat", "ruko", "cancel", "rehne do"}
INTENT_PROMPT = """You are the Manager of a YouTube video production team. Classify the owner's message (Hinglish).
Message: {text}
Return ONLY JSON: {{"intent": "new_video|status|show_script|approve|revise|team|chat", "topic": "", "instruction": ""}}
new_video = wants a new video (put the topic in "topic"). revise = wants changes to the current script (put them in "instruction").
chat = anything else."""
CHAT_SYSTEM = ("You are the Manager of a small faceless YouTube team (facts, history, geography, science, mystery; channel Verinomia). "
               "Reply in short Hinglish (Hindi in Latin letters), 1-2 sentences. Only talk about video planning. Never invent facts about what the team has done or promised; never mention accuracy percentages.")
HELP = ("Main tumhara Manager hoon. Bolo, jaise:\n• 'naya video: Bermuda Triangle ka sach'\n• 'status' — kaam kahan tak pahuncha\n"
        "• 'script dikhao'\n• 'approve' — script pakki (pehle puchunga)\n• 'script me hook tez karo'\n• 'team' — kaun kaun kya karta hai")


def _words(text: str) -> str:
    return re.sub(r"[^\w\s]", " ", text.lower(), flags=re.U).strip()


class ManagerChat:
    def __init__(self, hub: "Hub") -> None:
        self.hub = hub

    # ---------------------------------------------------------------- state
    @property
    def project_id(self) -> int | None:
        pid = self.hub.db.get_setting("manager_project", None)
        return int(pid) if pid else None

    def _set_project(self, pid: int) -> None:
        self.hub.db.set_setting("manager_project", int(pid))

    # ---------------------------------------------------------------- entry point
    async def handle(self, uid: int, chat_id: int, text: str, *, message_id: int = 0) -> str:
        text = " ".join((text or "").split())[:2000]
        if not text:
            return HELP
        conv = self.hub.extra["conv"]
        pending = conv.get(uid)
        if pending and pending["step"] == "manager_topic":
            conv.clear(uid)
            if _words(text) in NO:
                return "Theek hai, kuch nahi kiya."
            return await self._act(uid, chat_id, "new_video", text[:800], "", text, message_id)
        if pending and pending["step"] == "manager_confirm":
            return await self._confirm(uid, chat_id, pending["data"], text, message_id)
        intent, topic, instruction = self._rules(text)
        if intent == "chat" and await self.hub.llm.available():
            intent, topic, instruction = await self._llm_intent(text)
        return await self._act(uid, chat_id, intent, topic, instruction, text, message_id)

    # ---------------------------------------------------------------- understanding
    @staticmethod
    def _rules(text: str) -> tuple[str, str, str]:
        w = _words(text)
        m = re.match(r"^\s*(?:na+ya|na+yi|nya|new)\s+video\s*[:\-]?\s*(.*)$", text, re.I) or re.match(r"^\s*video\s+(?:banao|bana do|banana)\s*[:\-]?\s*(.*)$", text, re.I)
        if m:
            rest = m.group(1).strip()
            if not rest or set(_words(rest).split()) <= FILLER:  # "naya video topic" has no topic yet
                return "ask_topic", "", ""
            if len(rest) >= 5:
                return "new_video", rest, ""
        if w in ("team", "agents", "agent", "kaun kaun", "team dikhao"):
            return "team", "", ""
        if w in ("status", "progress", "kya hua", "kya chal raha hai", "kahan tak hua", "kaam kahan tak"):
            return "status", "", ""
        if w in ("script dikhao", "script dikha", "script", "script padho", "show script"):
            return "show_script", "", ""
        if w in ("approve", "approve karo", "approve kar do", "script approve"):
            return "approve", "", ""
        if w in ("help", "madad", "start"):
            return "help", "", ""
        if w in GREET:
            return "greet", "", ""
        if w in ACK:
            return "ack", "", ""
        return "chat", "", ""

    async def _llm_intent(self, text: str) -> tuple[str, str, str]:
        try:
            d = await self.hub.llm.chat_json(INTENT_PROMPT.format(text=text), max_tokens=300)
        except Exception:  # noqa: BLE001 - fall back to plain chat
            return "chat", "", ""
        d = d if isinstance(d, dict) else {}
        intent = str(d.get("intent", "chat"))
        if intent not in ("new_video", "status", "show_script", "approve", "revise", "team", "chat"):
            intent = "chat"
        topic, instr = " ".join(str(d.get("topic", "")).split())[:800], " ".join(str(d.get("instruction", "")).split())[:500]
        if intent == "new_video" and len(topic) < 5:
            intent = "chat"
        if intent == "revise" and len(instr) < 3:
            intent = "chat"
        return intent, topic, instr

    # ---------------------------------------------------------------- actions
    async def _act(self, uid: int, chat_id: int, intent: str, topic: str, instruction: str, text: str, message_id: int) -> str:
        hub, conv = self.hub, self.hub.extra["conv"]
        if intent == "help":
            return HELP
        if intent == "ask_topic":
            conv.set(uid, "manager_topic")
            return "Kis topic par video banani hai? Seedha topic likho, jaise: Bharat ki khoj, ya Bermuda Triangle ka sach."
        if intent == "greet":
            return "Namaste! Main tumhara Manager hoon. Naya video chahiye to bolo: 'naya video: <topic>'. Baaki sab ke liye 'help'."
        if intent == "ack":
            return "👍 Bolo, ab kya karna hai? ('naya video: <topic>' ya 'help')"
        if intent == "team":
            return team_text()
        if intent == "status":
            return self._status()
        if intent == "show_script":
            s = self._latest()
            return ("📜 " + s["content"][:3500]) if s else "Abhi koi script nahi hai. 'naya video: <topic>' bolo."
        if intent == "new_video" and set(_words(topic).split()) <= FILLER:
            return await self._act(uid, chat_id, "ask_topic", "", "", text, message_id)
        if intent == "new_video":
            if not await hub.llm.available():
                return "AI abhi band hai (Ollama chalu karo ya Settings me Cloud AI ON). Tab tak main video shuru nahi kar sakta."
            conv.set(uid, "manager_confirm", action="new_video", topic=topic)
            return (f"🎬 Naya video: \"{topic}\"\nMain Research → Accuracy → Script → Quality chalaunga (2-10 min, laptop pe). "
                    "Shuru karun? (haan / nahi)")
        if intent == "approve":
            s = self._latest()
            if not s or s["approval_status"] != "draft":
                return "Approve karne layak koi draft script nahi hai."
            conv.set(uid, "manager_confirm", action="approve", script_id=s["id"])
            return (f"Script v{s['version_number']} approve karun? Ek baar padh liya hai na, facts khud check kiye? (haan / nahi)")
        if intent == "revise":
            s = self._latest()
            if not s:
                return "Pehle script chahiye. 'naya video: <topic>' bolo."
            if not await hub.llm.available():
                return "AI abhi band hai, badlaav nahi kar sakta."
            conv.set(uid, "manager_confirm", action="revise", script_id=s["id"], instruction=instruction)
            return f"Script v{s['version_number']} me ye badlaav karun: \"{instruction}\"? (haan / nahi)"
        return await self._chat(text)

    async def _confirm(self, uid: int, chat_id: int, data: dict, text: str, message_id: int) -> str:
        hub, conv = self.hub, self.hub.extra["conv"]
        w = _words(text)
        if w in NO or w.split(" ")[0] in NO:
            conv.clear(uid)
            return "Theek hai, kuch nahi kiya."
        if not YES_RE.match(w):
            if data.get("action") == "new_video" and len(text) >= 5:  # not yes/no: the owner is correcting the topic
                topic = re.sub(r"^\s*topic\s*[:\-]\s*", "", text, flags=re.I)[:800]
                conv.set(uid, "manager_confirm", action="new_video", topic=topic)
                return f"Theek hai, topic badal diya: \"{topic}\"\nShuru karun? (haan / nahi)"
            conv.set(uid, "manager_confirm", **data)
            return "Seedha bolo: haan ya nahi."
        conv.clear(uid)
        act = data["action"]
        if act == "new_video":
            name = re.sub(r"\s+", " ", data["topic"])[:60]
            mins = re.search(r"(\d{1,2})\s*(?:min|mins|minute|minutes|मिनट)", text.lower())
            settings = {"target_seconds": int(mins.group(1)) * 60} if mins and 1 <= int(mins.group(1)) <= 30 else {}
            p = hub.projects.create_project(name, settings=settings)
            self._set_project(p["id"])
            job = hub.jobs.submit_job("video_pipeline", p["id"], {"project_id": p["id"], "topic": data["topic"]}, 3,
                                      idempotency_key=f"mgr:{uid}:{message_id}", chat_id=chat_id, title="Auto script (agents)")
            length = f" Length: ~{settings['target_seconds'] // 60} min." if settings else ""
            return f"✅ Shuru. Project '{name}' bana, job #{job['id']} chal rahi hai.{length} Khatam hote hi report bhejunga. ('status' se pooch sakte ho)"
        if act == "approve":
            s = hub.scripts.approve(int(data["script_id"]))
            hub.audit.record("script_approve", "ok", "script", s["id"], project=s["project_id"], via="manager")
            return f"✅ Script v{s['version_number']} approved."
        if act == "revise":
            s = hub.scripts.get(int(data["script_id"]))
            job = hub.jobs.submit_job("script_write", s["project_id"], {"project_id": s["project_id"], "text": data["instruction"],
                                                                        "revise_script_id": s["id"]}, 3,
                                      idempotency_key=f"mgr:{uid}:{message_id}", chat_id=chat_id, title="AI script badlaav")
            return f"✅ Badlaav ke liye job #{job['id']} chal rahi hai. Nayi version draft banegi."
        return "Ye kaam samajh nahi aaya."

    def _latest(self) -> dict | None:
        pid = self.project_id
        return self.hub.scripts.latest(pid) if pid else None

    def _status(self) -> str:
        jobs = self.hub.jobs.list_jobs(active_only=True, limit=5)
        if not jobs:
            last = self.hub.jobs.list_jobs(limit=1)
            why = f"\n{last[0]['error_message'][:300]}" if last and last[0].get("error_message") else ""
            return "Abhi koi kaam nahi chal raha." + (f" Aakhri job #{last[0]['id']}: {last[0]['status']}.{why}" if last else "")
        return "\n".join(f"⏳ job #{j['id']} {j.get('title') or j['job_type']} — {j['status']}"
                         f"{' · ' + j['stage'] if j.get('stage') else ''} ({int((j.get('progress') or 0) * 100)}%)" for j in jobs)

    async def _chat(self, text: str) -> str:
        if not await self.hub.llm.available():
            return HELP
        try:
            return (await self.hub.llm.chat(text, system=CHAT_SYSTEM, max_tokens=300, temperature=0.3)).strip()[:1500] or HELP
        except Exception:  # noqa: BLE001
            return HELP
