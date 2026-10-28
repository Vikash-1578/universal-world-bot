"""Script Studio + Storyboard Studio screens (Milestone 4)."""
from __future__ import annotations

import io
import time
from pathlib import Path

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Message

from app.scripts import parser
from app.scripts.inputs import read_text_file
from app.storage.files import check_upload, safe_name, sha256
from app.storyboards.service import SHOTS, TRANSITIONS
from app.telegram.callbacks.codec import make, parse
from app.telegram.keyboards.menus import confirm, nav, pager
from app.telegram.ui import ago, answer, fail, show

router = Router(name="studio")
PER = 6
STATUS_ICON = {"draft": "📝 draft", "approved": "✅ approved", "rejected": "❌ rejected", "superseded": "🗄 purana"}
SB_STATUS = {"none": "abhi nahi bana", "draft": "📝 draft (approval baaki)", "approved": "✅ approved",
             "changed": "⚠️ approve ke baad badla — dobara approval chahiye", "rejected": "❌ rejected"}


# ------------------------------------------------------------------ helpers
async def pick_project(target, hub, area: str, page: int = 0) -> None:
    rows, total = hub.projects.list_projects(offset=page * PER, limit=PER)
    title = "📜 Script Studio" if area == "ss" else "🎞 Storyboard Studio"
    if not rows:
        await show(target, f"{title}\n\nPehle ek project banao.", KB(inline_keyboard=[[B(text="🎬 Naya project", callback_data=make("m", "new"))], nav()]))
        return
    kb = [[B(text=f"{r['name'][:34]} · {r['status']}", callback_data=make(area, "open", r["id"]))] for r in rows]
    if total > PER:
        kb.append(pager(area, "pick", page, total, PER))
    kb.append(nav())
    await show(target, f"{title}\n\nKis project par kaam karna hai?", KB(inline_keyboard=kb))


async def send_long(message: Message, text: str, title: str = "") -> None:
    if len(text) <= 3800:
        await message.answer((title + "\n\n" if title else "") + text, parse_mode=None)
        return
    from aiogram.types import BufferedInputFile

    await message.answer_document(BufferedInputFile(text.encode("utf-8"), filename="script.txt"),
                                  caption=title[:200] or "Script", parse_mode=None)


def _msg(target) -> Message | None:
    return target.message if isinstance(target, CallbackQuery) and isinstance(target.message, Message) else (
        target if isinstance(target, Message) else None)


# ------------------------------------------------------------------ Script Studio
async def show_script(target, hub, pid: int) -> None:
    p = hub.projects.get_project(pid)
    latest = hub.scripts.latest(pid)
    approved = hub.scripts.approved(pid)
    llm_ok = await hub.llm.available()
    lines = [f"📜 Script Studio — {p['name']}"]
    if not latest:
        lines.append("\nAbhi koi script nahi hai.")
    else:
        ps = parser.parse(latest["content"])
        lines += [f"\nLatest: v{latest['version_number']} · {STATUS_ICON.get(latest['approval_status'], latest['approval_status'])}",
                  f"Title: {ps.title or '-'}",
                  f"Scenes: {len(ps.scenes)} · Characters: {', '.join(ps.characters[:8]) or '-'}",
                  f"Andaazan length: ~{ps.seconds:.0f}s (target {p['settings'].get('target_seconds')}s)"]
        if approved and approved["id"] != latest["id"]:
            lines.append(f"Approved abhi bhi: v{approved['version_number']}")
    lines.append("\n🤖 AI: " + ("chalu" if llm_ok else "band (Ollama nahi mila / Cloud AI OFF) — khud likhi script chalegi"))
    kb = [[B(text="✍️ Script bhejo (text/file)", callback_data=make("ss", "send", pid))],
          [B(text="🤖 AI se likhwao", callback_data=make("ss", "ai", pid))]]
    if latest:
        kb.append([B(text="👁 Poori padho", callback_data=make("ss", "view", latest["id"])),
                   B(text="🕘 Versions", callback_data=make("ss", "vers", pid))])
        if latest["approval_status"] == "draft":
            kb.append([B(text="✅ Approve", callback_data=make("ss", "approve", latest["id"])),
                       B(text="❌ Reject", callback_data=make("ss", "reject", latest["id"]))])
        kb.append([B(text="🔁 AI se badlaav", callback_data=make("ss", "revise", latest["id"]))])
    if approved:
        kb.append([B(text="🎞 Storyboard par chalo", callback_data=make("sb", "open", pid))])
    kb.append(nav(back="m|script", refresh=f"ss|open|{pid}"))
    await show(target, "\n".join(lines), KB(inline_keyboard=kb))


@router.callback_query(F.data.func(lambda d: (c := parse(d)) is not None and c.area == "ss"))
async def cb_script(cb: CallbackQuery, hub) -> None:
    c = parse(cb.data)
    assert c is not None
    conv = hub.extra["conv"]
    try:
        a = c.action
        if a == "pick":
            await answer(cb)
            await pick_project(cb, hub, "ss", c.int(0))
        elif a == "open":
            await answer(cb)
            await show_script(cb, hub, c.int(0))
        elif a == "send":
            pid = c.int(0)
            hub.projects.get_project(pid)
            conv.set(cb.from_user.id, "script_text", project_id=pid)
            await answer(cb)
            await show(cb, "✍️ Script bhejo:\n• Text message me paste karo, ya\n• .txt / .docx / .pdf file bhejo, ya\n"
                           "• 🎤 voice message (Cloud AI ON ho tab)\n• Photo bhejoge to wo reference image ki tarah save hogi\n\n"
                           "Format:\nTitle: Kahani ka naam\n[Scene 1: Jungle, subah]\nNarrator: ...\nKhargosh: (khush) ...",
                       KB(inline_keyboard=[nav(back=f"ss|open|{pid}", cancel=True)]))
        elif a == "ai":
            pid = c.int(0)
            if not await hub.llm.available():
                await answer(cb)
                await show(cb, "🤖 AI abhi band hai.\n\n• Free local AI: ollama.com se Ollama install karo → PowerShell me `ollama pull llama3.1:8b`\n"
                               "• Ya ⚙️ Settings → Cloud AI ON (keys.txt me key)\n• Ya ✍️ apni script bhejo",
                           KB(inline_keyboard=[nav(back=f"ss|open|{pid}")]))
                return
            conv.set(cb.from_user.id, "script_idea", project_id=pid)
            await answer(cb)
            await show(cb, "🤖 Kahani ka idea likho (1-3 line). Jaise: 'Kachhua aur khargosh ki race, is baar twist ke saath'",
                       KB(inline_keyboard=[nav(back=f"ss|open|{pid}", cancel=True)]))
        elif a == "revise":
            s = hub.scripts.get(c.int(0))
            if not await hub.llm.available():
                await answer(cb, "AI band hai — script khud edit karke ✍️ se bhejo", alert=True)
                return
            conv.set(cb.from_user.id, "script_revise", project_id=s["project_id"], script_id=s["id"])
            await answer(cb)
            await show(cb, f"🔁 v{s['version_number']} me kya badalna hai? (Jaise: 'end me ek joke daalo', 'scene 2 chhota karo')\n"
                           "Nayi version banegi, purani safe rahegi.", KB(inline_keyboard=[nav(back=f"ss|open|{s['project_id']}", cancel=True)]))
        elif a == "view":
            s = hub.scripts.get(c.int(0))
            await answer(cb)
            m = _msg(cb)
            if m:
                await send_long(m, s["content"], f"📜 Script v{s['version_number']} ({s['approval_status']})")
        elif a == "vers":
            pid = c.int(0)
            vs = hub.scripts.versions(pid)[:10]
            kb = [[B(text=f"v{v['version_number']} · {STATUS_ICON.get(v['approval_status'], v['approval_status'])} · {ago(v['created_at'])}",
                     callback_data=make("ss", "ver", v["id"]))] for v in vs]
            kb.append(nav(back=f"ss|open|{pid}"))
            await answer(cb)
            await show(cb, "🕘 Script versions (naya upar)", KB(inline_keyboard=kb))
        elif a == "ver":
            s = hub.scripts.get(c.int(0))
            ps = parser.parse(s["content"])
            kb = [[B(text="👁 Poori padho", callback_data=make("ss", "view", s["id"]))]]
            if s["approval_status"] in ("draft", "rejected", "superseded"):
                kb.append([B(text="✅ Isko approve karo", callback_data=make("ss", "approve", s["id"]))])
            kb.append(nav(back=f"ss|vers|{s['project_id']}"))
            await answer(cb)
            await show(cb, f"📜 v{s['version_number']} · {s['approval_status']} · {ago(s['created_at'])}\n"
                           f"Title: {ps.title or '-'} · {len(ps.scenes)} scenes · ~{ps.seconds:.0f}s\n"
                           f"Characters: {', '.join(ps.characters) or '-'}", KB(inline_keyboard=kb))
        elif a == "approve":
            s = hub.scripts.get(c.int(0))
            await answer(cb)
            await show(cb, f"✅ Script v{s['version_number']} approve karna hai? Storyboard isi se banega.",
                       confirm("ss", "approve_ok", s["id"], no_back=f"ss|open|{s['project_id']}"))
        elif a == "approve_ok":
            s = hub.scripts.approve(c.int(0))
            hub.audit.record("script_approve", "ok", "script", s["id"], project=s["project_id"])
            await answer(cb, f"Script v{s['version_number']} approved")
            await show_script(cb, hub, s["project_id"])
        elif a == "reject":
            s = hub.scripts.reject(c.int(0))
            await answer(cb, "Reject kiya")
            await show_script(cb, hub, s["project_id"])
        else:
            await answer(cb, "Ye button purana ho gaya.", alert=True)
    except ValueError:
        await answer(cb, "Ye button purana ho gaya.", alert=True)
    except Exception as e:  # noqa: BLE001
        await fail(cb, e)


# ------------------------------------------------------------------ Storyboard Studio
async def show_storyboard(target, hub, pid: int) -> None:
    p = hub.projects.get_project(pid)
    st = hub.storyboards.state(pid)
    approved_script = hub.scripts.approved(pid)
    scenes = hub.storyboards.scenes(pid)
    lines = [f"🎞 Storyboard — {p['name']}", f"Halat: {SB_STATUS.get(st.get('status', 'none'), st.get('status'))}"]
    if not approved_script:
        lines.append("\n⚠️ Pehle Script Studio me script approve karo.")
    else:
        lines.append(f"Script: v{approved_script['version_number']} (approved)")
        if st.get("script_id") and st.get("script_id") != approved_script["id"]:
            lines.append("⚠️ Script badal gayi hai — naya draft banao.")
    if scenes:
        total = sum(s["duration_seconds"] for s in scenes)
        lines.append(f"Scenes: {len(scenes)} · ~{total:.0f}s · banaya: {st.get('source', '-')}")
    if st.get("note"):
        lines.append(st["note"])
    kb: list[list[B]] = []
    if approved_script:
        if st.get("status") == "approved":
            kb.append([B(text="♻️ Naya draft (approved hata ke)", callback_data=make("sb", "draft", pid, "replace"))])
        else:
            kb.append([B(text="🧠 Draft banao" if not scenes else "🧠 Draft dobara banao", callback_data=make("sb", "draft", pid))])
    if scenes:
        kb.append([B(text="🎞 Scenes dekho / edit", callback_data=make("sb", "sc", pid, 0))])
        if st.get("status") in ("draft", "changed", "rejected"):
            kb.append([B(text="✅ Storyboard approve", callback_data=make("sb", "approve", pid)),
                       B(text="❌ Reject", callback_data=make("sb", "reject", pid))])
    kb.append(nav(back="m|storyboard", refresh=f"sb|open|{pid}"))
    await show(target, "\n".join(lines), KB(inline_keyboard=kb))


async def show_scene(target, hub, pid: int, idx: int) -> None:
    scenes = hub.storyboards.scenes(pid)
    if not scenes:
        await show_storyboard(target, hub, pid)
        return
    idx = max(0, min(len(scenes) - 1, idx))
    s = scenes[idx]
    sid = s["id"]
    kb = [
        [B(text="◀", callback_data=make("sb", "sc", pid, idx - 1)) if idx > 0 else B(text=" ", callback_data=make("m", "noop")),
         B(text=f"{idx + 1}/{len(scenes)}", callback_data=make("m", "noop")),
         B(text="▶", callback_data=make("sb", "sc", pid, idx + 1)) if idx + 1 < len(scenes) else B(text=" ", callback_data=make("m", "noop"))],
        [B(text="🎥 Shot badlo", callback_data=make("sb", "shot", pid, sid, idx)),
         B(text="↪ Transition", callback_data=make("sb", "tr", pid, sid, idx))],
        [B(text="⏱ -2s", callback_data=make("sb", "dur", pid, sid, idx, "m")), B(text="⏱ +2s", callback_data=make("sb", "dur", pid, sid, idx, "p"))],
        [B(text="📝 Description", callback_data=make("sb", "edit", pid, sid, "description")),
         B(text="📍 Jagah", callback_data=make("sb", "edit", pid, sid, "environment_ref"))],
        [B(text="⬆ Upar", callback_data=make("sb", "mv", pid, sid, idx, "u")), B(text="⬇ Neeche", callback_data=make("sb", "mv", pid, sid, idx, "d")),
         B(text="🔁 AI se dobara", callback_data=make("sb", "regen", pid, sid))],
        nav(back=f"sb|open|{pid}", refresh=f"sb|sc|{pid}|{idx}"),
    ]
    await show(target, hub.storyboards.scene_text(s, len(scenes)), KB(inline_keyboard=kb))


@router.callback_query(F.data.func(lambda d: (c := parse(d)) is not None and c.area == "sb"))
async def cb_storyboard(cb: CallbackQuery, hub) -> None:
    c = parse(cb.data)
    assert c is not None
    sb = hub.storyboards
    try:
        a = c.action
        if a == "pick":
            await answer(cb)
            await pick_project(cb, hub, "sb", c.int(0))
        elif a == "open":
            await answer(cb)
            await show_storyboard(cb, hub, c.int(0))
        elif a == "draft":
            pid = c.int(0)
            replace = c.arg(1) == "replace"
            if replace:
                token = hub.approvals.request("storyboard_replace", pid)
                await answer(cb)
                await show(cb, "♻️ Approved storyboard hata ke naya draft banana hai? (Approved wala version history me safe rahega.)",
                           confirm("sb", "draft_ok", pid, token, no_back=f"sb|open|{pid}"))
                return
            await _submit_draft(cb, hub, pid, False)
        elif a == "draft_ok":
            pid = c.int(0)
            hub.approvals.consume(c.arg(1), "storyboard_replace", pid)
            await _submit_draft(cb, hub, pid, True)
        elif a == "sc":
            await answer(cb)
            await show_scene(cb, hub, c.int(0), c.int(1))
        elif a in ("shot", "tr"):
            pid, sid, idx = c.int(0), c.int(1), c.int(2)
            s = sb.scene(pid, sid)
            opts, key = (SHOTS, "shot") if a == "shot" else (TRANSITIONS, "transition")
            cur = s["camera"].get(key)
            nxt = opts[(opts.index(cur) + 1) % len(opts)] if cur in opts else opts[0]
            sb.update_scene(pid, sid, {key: nxt})
            await answer(cb, f"{key}: {nxt}")
            await show_scene(cb, hub, pid, idx)
        elif a == "dur":
            pid, sid, idx = c.int(0), c.int(1), c.int(2)
            s = sb.scene(pid, sid)
            d = max(1.0, s["duration_seconds"] + (2 if c.arg(3) == "p" else -2))
            sb.update_scene(pid, sid, {"duration_seconds": d})
            await answer(cb, f"{d:.0f}s")
            await show_scene(cb, hub, pid, idx)
        elif a == "mv":
            pid, sid, idx = c.int(0), c.int(1), c.int(2)
            new = idx + (0 if c.arg(3) == "u" else 2)  # positions are 1-based
            sb.reorder_scene(pid, sid, max(1, new))
            await answer(cb, "Jagah badli")
            await show_scene(cb, hub, pid, max(0, new - 1))
        elif a == "edit":
            pid, sid, field = c.int(0), c.int(1), c.arg(2)
            if field not in ("description", "environment_ref"):
                raise ValueError("bad field")
            sb.scene(pid, sid)
            hub.extra["conv"].set(cb.from_user.id, "sb_edit", project_id=pid, scene_id=sid, field=field)
            await answer(cb)
            await show(cb, "📝 Naya description likho:" if field == "description" else "📍 Jagah ka naam/description likho:",
                       KB(inline_keyboard=[nav(back=f"sb|sc|{pid}|0", cancel=True)]))
        elif a == "regen":
            pid, sid = c.int(0), c.int(1)
            if not await hub.llm.available():
                await answer(cb, "AI band hai — 📝/📍/🎥 se khud badlo", alert=True)
                return
            m = _msg(cb)
            job = hub.jobs.submit_job("scene_regen", pid, {"project_id": pid, "scene_id": sid}, 3,
                                      idempotency_key=f"regen:{pid}:{sid}:{int(time.time() // 30)}", chat_id=m.chat.id if m else None)
            await answer(cb, "AI scene dobara bana raha hai")
            if m:
                from app.telegram.handlers.jobs import send_card

                await send_card(m, hub, job["id"])
        elif a == "approve":
            pid = c.int(0)
            await answer(cb)
            await show(cb, "✅ Storyboard approve karna hai? Iske baad hi animation/render shuru hoga.",
                       confirm("sb", "approve_ok", pid, no_back=f"sb|open|{pid}"))
        elif a == "approve_ok":
            pid = c.int(0)
            sb.approve(pid)
            hub.audit.record("storyboard_approve", "ok", "project", pid)
            await answer(cb, "Storyboard approved ✅")
            await show_storyboard(cb, hub, pid)
        elif a == "reject":
            pid = c.int(0)
            sb.reject(pid, "owner ne reject kiya")
            await answer(cb, "Reject kiya")
            await show_storyboard(cb, hub, pid)
        else:
            await answer(cb, "Ye button purana ho gaya.", alert=True)
    except ValueError:
        await answer(cb, "Ye button purana ho gaya.", alert=True)
    except Exception as e:  # noqa: BLE001
        await fail(cb, e)


async def _submit_draft(cb: CallbackQuery, hub, pid: int, replace: bool) -> None:
    if not hub.scripts.approved(pid):
        await answer(cb, "Pehle script approve karo", alert=True)
        return
    m = _msg(cb)
    job = hub.jobs.submit_job("storyboard_draft", pid, {"project_id": pid, "replace": replace, "use_ai": True}, 3,
                              idempotency_key=f"sbdraft:{pid}:{m.message_id if m else 0}:{int(replace)}",
                              chat_id=m.chat.id if m else None, title="Storyboard draft")
    await answer(cb, "Storyboard draft line me laga")
    if m:
        from app.telegram.handlers.jobs import send_card

        await send_card(m, hub, job["id"])


# ------------------------------------------------------------------ conversation input
async def on_text(message: Message, hub, step: str, data: dict) -> bool:
    uid = message.from_user.id if message.from_user else 0
    conv = hub.extra["conv"]
    text = (message.text or "").strip()
    if step == "script_text":
        v = hub.scripts.create_version(int(data["project_id"]), text)
        conv.clear(uid)
        await message.answer(f"✅ Script v{v['version_number']} save hui (draft).", parse_mode=None)
        await show_script(message, hub, int(data["project_id"]))
        return True
    if step in ("script_idea", "script_revise"):
        pid = int(data["project_id"])
        inputs = {"project_id": pid, "text": text[:800]}
        if step == "script_revise":
            inputs["revise_script_id"] = int(data["script_id"])
        job = hub.jobs.submit_job("script_write", pid, inputs, 3, idempotency_key=f"sw:{uid}:{message.message_id}",
                                  chat_id=message.chat.id, title="AI script" if step == "script_idea" else "AI script badlaav")
        conv.clear(uid)
        from app.telegram.handlers.jobs import send_card

        await send_card(message, hub, job["id"])
        return True
    if step == "sb_edit":
        pid, sid = int(data["project_id"]), int(data["scene_id"])
        hub.storyboards.update_scene(pid, sid, {data["field"]: text})
        conv.clear(uid)
        idx = next((i for i, s in enumerate(hub.storyboards.scenes(pid)) if s["id"] == sid), 0)
        await show_scene(message, hub, pid, idx)
        return True
    return False


async def on_media(message: Message, hub, step: str, data: dict) -> bool:
    """Documents, voice and photos sent while the bot is waiting for a script."""
    if step != "script_text":
        return False
    pid = int(data["project_id"])
    uid = message.from_user.id if message.from_user else 0
    bot = message.bot
    folder = hub.projects.folder(pid, "assets", "inputs")
    if message.document:
        doc = message.document
        name = check_upload("document" if Path(doc.file_name or "").suffix.lower() in (".pdf", ".docx") else "text",
                            doc.file_name or "script.txt", doc.file_size or 0)
        dest = folder / f"{int(time.time())}_{name}"
        await bot.download(doc, destination=dest)
        text = read_text_file(dest)
        _record_asset(hub, pid, "script_source", dest, {"from": "telegram_document"})
        v = hub.scripts.create_version(pid, text)
        hub.extra["conv"].clear(uid)
        await message.answer(f"✅ File se script v{v['version_number']} bani (draft).", parse_mode=None)
        await show_script(message, hub, pid)
        return True
    if message.voice or message.audio:
        from app.audio.stt import transcribe

        media = message.voice or message.audio
        check_upload("audio", getattr(media, "file_name", None) or "voice.ogg", media.file_size or 1)
        buf = io.BytesIO()
        await bot.download(media, destination=buf)
        lang = {"hindi": "hi", "english": "en"}.get(hub.projects.get_project(pid)["settings"].get("language", ""), "")
        await message.answer("🎤 Awaaz ko text me badal raha hoon (Groq Whisper, cloud)...", parse_mode=None)
        text = await transcribe(buf.getvalue(), "voice.ogg", keys=hub.settings.keys_for("groq"),
                                cloud_enabled=hub.cloud_enabled, language=lang)
        v = hub.scripts.create_version(pid, text)
        hub.extra["conv"].clear(uid)
        await message.answer(f"✅ Voice se script v{v['version_number']} bani (draft). Ek baar padh ke check kar lena.", parse_mode=None)
        await show_script(message, hub, pid)
        return True
    if message.photo:
        ph = message.photo[-1]
        check_upload("image", "ref.jpg", ph.file_size or 1)
        dest = folder / f"ref_{int(time.time())}_{safe_name(ph.file_unique_id)}.jpg"
        await bot.download(ph, destination=dest)
        _record_asset(hub, pid, "reference_image", dest, {"from": "telegram_photo"})
        await message.answer("🖼 Reference photo project me save ho gayi. Ab script bhejo.", parse_mode=None)
        return True
    return False


def _record_asset(hub, pid: int, kind: str, path: Path, meta: dict) -> None:
    from app.storage.db import dumps

    rel = str(path.relative_to(hub.settings.data_dir)).replace("\\", "/")
    hub.db.execute("INSERT OR IGNORE INTO assets (asset_type, relative_path, checksum, metadata_json, protected, project_id, created_at) "
                   "VALUES (?, ?, ?, ?, 1, ?, ?)", (kind, rel, sha256(path), dumps(meta), pid, time.time()))
