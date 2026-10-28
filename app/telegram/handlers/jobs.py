"""Job Queue screens + live job cards (one message per job, edited as it progresses — not a message per event)."""
from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Message

from app.scheduler import service as S
from app.storage.db import loads
from app.telegram.callbacks.codec import make, parse
from app.telegram.keyboards.menus import confirm, nav, pager
from app.telegram.ui import ago, answer, bar, fail, show

router = Router(name="jobs")
PER = 6


def card_text(hub, job: dict) -> str:
    lines = [f"⚙️ Job #{job['id']} — {job['title'] or job['job_type']}",
             f"Halat: {S.LABEL.get(job['status'], job['status'])}"]
    if job["status"] in (S.RUNNING, S.CANCEL_REQ, S.PAUSED, S.RETRY, S.WAIT_RES):
        lines.append(f"{bar(job['progress'])} {int(job['progress'] * 100)}%  {job['stage'] or ''}")
    if job["control"] == "pause" and job["status"] == S.RUNNING:
        lines.append("⏸ Pause maanga hai — ye step khatam hote hi rukega.")
    if job["status"] == S.CANCEL_REQ:
        lines.append("🛑 Cancel maanga hai — current step ke baad rukega.")
    if job["status"] == S.WAIT_APPROVAL:
        out = loads(job["output_manifest"], {}) or {}
        lines.append(f"✋ Approval chahiye: {out.get('pending_approval', '?')}")
    if job["status"] == S.RETRY and job["not_before"] > time.time():
        lines.append(f"🔁 {int(job['not_before'] - time.time())}s baad dobara try (attempt {job['attempt_count']}/{job['max_attempts']})")
    if job["error_message"] and job["status"] in (S.FAILED, S.RETRY):
        lines.append(f"Wajah: {job['error_message']}")
    stages = hub.jobs.stages(job["id"])
    if stages:
        icon = {S.COMPLETED: "✅", S.RUNNING: "⚙️", S.FAILED: "❌"}
        lines.append("Steps: " + "  ".join(f"{icon.get(s['status'], '·')}{s['stage_name']}" for s in stages[-6:]))
    if job["project_id"]:
        lines.append(f"Project #{job['project_id']}")
    lines.append(f"Priority {job['priority']} · bana {ago(job['created_at'])}")
    return "\n".join(lines)


def card_kb(job: dict) -> KB:
    jid, st = job["id"], job["status"]
    row: list[B] = []
    if st in (S.QUEUED, S.RETRY, S.WAIT_RES, S.RUNNING) and job["control"] != "pause":
        row.append(B(text="⏸ Pause", callback_data=make("j", "pause", jid)))
    if st == S.PAUSED:
        row.append(B(text="▶ Resume", callback_data=make("j", "resume", jid)))
    if st == S.WAIT_APPROVAL:
        row.append(B(text="✅ Approve", callback_data=make("j", "approve", jid)))
    if st not in S.FINAL and st != S.CANCEL_REQ:
        row.append(B(text="🛑 Cancel", callback_data=make("j", "cancel", jid)))
    if st in (S.FAILED, S.CANCELLED):
        row.append(B(text="🔁 Retry", callback_data=make("j", "retry", jid)))
    rows = [row] if row else []
    if st in (S.QUEUED, S.RETRY, S.WAIT_RES, S.PAUSED):
        rows.append([B(text="⬆ Priority", callback_data=make("j", "prio", jid, max(1, job["priority"] - 1))),
                     B(text="⬇ Priority", callback_data=make("j", "prio", jid, min(9, job["priority"] + 1)))])
    rows.append(nav(back="m|jobs", refresh=f"j|open|{jid}"))
    return KB(inline_keyboard=rows)


async def send_card(message: Message, hub, job_id: int) -> None:
    job = hub.jobs.get_job(job_id)
    sent = await message.answer(card_text(hub, job), reply_markup=card_kb(job), parse_mode=None)
    hub.db.update("jobs", job_id, {"card_message_id": sent.message_id, "chat_id": message.chat.id})


async def show_list(target, hub, page: int, project_id: int | None = None) -> None:
    jobs = hub.jobs.list_jobs(active_only=project_id is None, project_id=project_id, offset=page * PER, limit=PER + 1)
    more = len(jobs) > PER
    jobs = jobs[:PER]
    head = f"⏳ Job Queue{f' — project #{project_id}' if project_id else ' (chalu jobs)'}"
    text = head + ("\n\nAbhi koi job nahi." if not jobs else "")
    kb = [[B(text=f"#{j['id']} {S.LABEL.get(j['status'], j['status'])[:14]} · {(j['title'] or j['job_type'])[:22]}",
             callback_data=make("j", "open", j["id"]))] for j in jobs]
    if page > 0 or more:
        kb.append(pager("j", "list", page, (page + 2) * PER if more else (page + 1) * PER, PER, project_id or 0))
    kb.append(nav(refresh=f"j|list|{page}|{project_id or 0}"))
    await show(target, text, KB(inline_keyboard=kb))


@router.callback_query(F.data.func(lambda d: (c := parse(d)) is not None and c.area == "j"))
async def cb_jobs(cb: CallbackQuery, hub) -> None:
    c = parse(cb.data)
    assert c is not None
    try:
        a = c.action
        if a == "list":
            await answer(cb)
            await show_list(cb, hub, c.int(0), c.int(1) or None if len(c.args) > 1 else None)
            return
        jid = c.int(0)
        if a == "open":
            await answer(cb)
        elif a == "pause":
            r = hub.jobs.pause_job(jid)
            await answer(cb, "Paused" if r == "paused" else "Current step ke baad rukega")
        elif a == "resume":
            hub.jobs.resume_job(jid)
            await answer(cb, "Wapas line me")
        elif a == "cancel":
            await answer(cb)
            await show(cb, f"🛑 Job #{jid} cancel karna hai?", confirm("j", "cancel_ok", jid, no_back=f"j|open|{jid}"))
            return
        elif a == "cancel_ok":
            r = hub.jobs.cancel_job(jid)
            hub.audit.record("job_cancel", r, "job", jid)
            await answer(cb, "Cancel ho gaya" if r == "cancelled" else "Current step ke baad rukega")
        elif a == "retry":
            hub.jobs.retry_job(jid)
            await answer(cb, "Dobara line me")
        elif a == "prio":
            p = hub.jobs.change_priority(jid, c.int(1))
            await answer(cb, f"Priority {p}")
        elif a == "approve":
            hub.jobs.approve_job(jid)
            hub.audit.record("job_approve", "ok", "job", jid)
            await answer(cb, "Approved, aage badh raha hai")
        else:
            await answer(cb, "Ye button purana ho gaya.", alert=True)
            return
        job = hub.jobs.get_job(jid)
        await show(cb, card_text(hub, job), card_kb(job))
        if isinstance(cb.message, Message):
            hub.db.update("jobs", jid, {"card_message_id": cb.message.message_id, "chat_id": cb.message.chat.id})
    except ValueError:
        await answer(cb, "Ye button purana ho gaya.", alert=True)
    except Exception as e:  # noqa: BLE001
        await fail(cb, e)


class CardUpdater:
    """Listens to scheduler events and edits the job's card (at most every 3 s per job)."""

    def __init__(self, hub) -> None:
        self.hub = hub
        self.last: dict[int, float] = {}

    async def __call__(self, topic: str, data: dict) -> None:
        jid = data.get("job_id")
        bot = self.hub.bot
        if not jid or bot is None:
            return
        final = topic == "job.status"
        now = time.time()
        if not final and now - self.last.get(jid, 0) < 3:
            return
        self.last[jid] = now
        job = self.hub.jobs.get_job(jid)
        if not job["chat_id"] or not job["card_message_id"]:
            return
        try:
            await bot.edit_message_text(card_text(self.hub, job), chat_id=job["chat_id"], message_id=job["card_message_id"],
                                        reply_markup=card_kb(job), parse_mode=None)
        except TelegramBadRequest:
            pass
        if final and data.get("status") in (S.COMPLETED, S.FAILED, S.WAIT_APPROVAL):
            note = {S.COMPLETED: "✅ Job #{} ho gaya", S.FAILED: "❌ Job #{} fail hua", S.WAIT_APPROVAL: "✋ Job #{} tumhari approval ka wait kar raha"}
            try:
                await bot.send_message(job["chat_id"], note[data["status"]].format(jid), parse_mode=None,
                                       reply_to_message_id=job["card_message_id"])
            except TelegramBadRequest:
                pass
