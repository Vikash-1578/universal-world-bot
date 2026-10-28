"""🎬 Nayi video — guided step-by-step flow (callback area "w"). One screen = one decision, few buttons.

    type (2D)  ->  story (paste / file / AI idea)  ->  story review  ->  characters & places  ->  voices  ->  final check  ->  video

The next step is worked out from the project's data (no hidden wizard state), so "▶ Aage badho" on a project
always lands on the right screen, even after a restart. Owner clicks are the approvals (script, storyboard, final).
"""
from __future__ import annotations

import time
from pathlib import Path

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as KB, InputMediaPhoto, Message

from app.scripts import parser
from app.storage.files import check_upload
from app.telegram.callbacks.codec import make, parse
from app.telegram.keyboards.menus import nav
from app.telegram.ui import answer, fail, show

router = Router(name="wizard")

GENRES = {"seekh": "👶 Seekh wali (moral)", "comedy": "😂 Comedy", "adventure": "🗺 Adventure", "dosti": "🤝 Dosti / parivaar",
          "pauranik": "🛕 Pauranik / itihaas", "darawni": "👻 Halki darawni"}
GENRE_IDEA = {"seekh": "a kids moral story with a clear lesson", "comedy": "a funny story with jokes and a happy ending",
              "adventure": "an exciting adventure with a small danger and a brave choice", "dosti": "a warm story about friendship and family",
              "pauranik": "a story inspired by Indian mythology or history, respectful and simple", "darawni": "a mildly spooky story for kids with a twist and no gore"}
LENGTHS = (30, 60, 120)
PLACEHOLDER = "Nayi kahani"


def _m(target) -> Message | None:
    if isinstance(target, CallbackQuery):
        return target.message if isinstance(target.message, Message) else None
    return target


# ------------------------------------------------------------------ status helpers
def missing_pictures(hub, pid: int) -> list[str]:
    from app.telegram.handlers.library import missing_images, project_roles

    roles = project_roles(hub, pid)
    cast = hub.library.casting(pid)
    return [r for _k, r in roles if r not in cast] + list(missing_images(hub, pid, roles))


def next_step(hub, pid: int) -> str:
    if not hub.scripts.approved(pid):
        return "story" if hub.scripts.latest(pid) else "start"
    if missing_pictures(hub, pid):
        return "chars"
    return "check"


STEP_LABEL = {"start": "📖 Kahani do", "story": "📖 Kahani check karo", "chars": "🧍 Characters & jagah", "check": "✅ Final check & video"}


# ------------------------------------------------------------------ auto casting
def auto_cast(hub, pid: int) -> None:
    """Give every script role a library item: own item with a picture > ready template > new empty item."""
    from app.characters import templates
    from app.telegram.handlers.library import K, project_roles

    lib = hub.library
    cast = lib.casting(pid)
    for k, role in project_roles(hub, pid):
        if role in cast:
            continue
        kind = K[k]
        own, tmpl = lib.suggest_for(role, kind)
        pick = next((o for o in own if ("background" if kind == "environment" else "main") in lib.get(o["id"])["files"]), None)
        if pick is None and tmpl:
            rows = hub.db.all("SELECT id FROM library_items WHERE template_id = ?", (tmpl[0]["id"],))
            pick = lib.get(rows[0]["id"]) if rows else lib.from_template(tmpl[0]["id"])
        if pick is None and own:
            pick = own[0]
        if pick is None:
            s = hub.scripts.approved(pid) or hub.scripts.latest(pid)
            title = parser.parse(s["content"]).title if s else ""
            pick = lib.create_item(kind, role, {"style": templates.catalog()["style"], "story": title[:120]})
        lib.cast(pid, role, pick["id"])
        hub.audit.record("auto_cast", "ok", "project", pid, role=role, item=pick["id"])


# ------------------------------------------------------------------ screens
async def start(target, hub) -> None:
    kb = [[B(text="🎨 2D cartoon", callback_data=make("w", "type", "2d"))],
          [B(text="🧊 3D (Blender)", callback_data=make("p", "type", "3d"))],
          [B(text="🖼 Images + narration", callback_data=make("p", "type", "slideshow"))],
          nav()]
    await show(target, "🎬 Nayi video\n\nKis tarah ki video banani hai?", KB(inline_keyboard=kb))


async def story_input(target, hub) -> None:
    kb = [[B(text="📋 Kahani paste karo", callback_data=make("w", "paste"))],
          [B(text="📄 File bhejo (PDF / Word / TXT)", callback_data=make("w", "file"))],
          [B(text="🤖 AI se kahani banwao", callback_data=make("w", "ai"))],
          nav(back="w|start")]
    await show(target, "🎨 2D cartoon — Step 1: Kahani\n\nKahani kaise doge?", KB(inline_keyboard=kb))


async def story_review(target, hub, pid: int) -> None:
    p = hub.projects.get_project(pid)
    s = hub.scripts.latest(pid)
    if not s:
        await story_input(target, hub)
        return
    ps = parser.parse(s["content"])
    talkers = [c for c in ps.characters]
    lines = [f"📖 Step 1: Kahani — {p['name']}", "",
             f"Title: {ps.title or '-'}", f"Scenes: {len(ps.scenes)} · lambai ~{ps.seconds:.0f}s",
             f"Characters: {', '.join(talkers) or '— (sirf narrator)'}"]
    if not talkers:
        lines.append("\n⚠️ Is kahani me koi character bolta nahi. 🔁 AI se badlaav me likho: 'characters ke dialogue daalo'.")
    kb = [[B(text="👁 Poori kahani padho", callback_data=make("ss", "view", s["id"]))],
          [B(text="🔁 AI se badlaav", callback_data=make("ss", "revise", s["id"]))],
          [B(text="✅ Theek hai, aage ▶", callback_data=make("w", "okstory", pid, s["id"]))],
          nav(back=f"p|open|{pid}")]
    await show(target, "\n".join(lines), KB(inline_keyboard=kb))


async def chars(target, hub, pid: int) -> None:
    from app.telegram.handlers.library import missing_images, project_roles

    auto_cast(hub, pid)
    roles = project_roles(hub, pid)
    cast = hub.library.casting(pid)
    no_img = missing_images(hub, pid, roles)
    lines = [f"🧍 Step 2: Characters & jagah — {hub.projects.get_project(pid)['name']}", ""]
    for k, role in roles:
        c = cast.get(role)
        ok = c and role not in no_img
        lines.append(f"{'✅' if ok else '⚠️'} {'🧍' if k == 'c' else '🏞'} {role} → {c['name'] if c else '-'}{'' if ok else ' (image nahi)'}")
    kb = [[B(text="🖼 Sabki photo dekho", callback_data=make("w", "photos", pid))]]
    if no_img:
        lines += ["", f"{len(no_img)} ki image nahi hai. Bina image video nahi banegi (putla nahi lagayenge)."]
        kb.append([B(text=f"🎨 In {len(no_img)} ki AI image banao", callback_data=make("w", "aiall", pid))])
    kb.append([B(text="🔄 Kisi ko badlo / apni image do", callback_data=make("lb", "cast", pid))])
    if not no_img:
        kb.append([B(text="🔁 Image galat hai? Sabki dobara banao", callback_data=make("w", "redo", pid))])
        kb.append([B(text="✅ Sab theek, aage ▶", callback_data=make("w", "voice", pid))])
    kb.append(nav(back=f"w|story|{pid}", refresh=f"w|chars|{pid}"))
    await show(target, "\n".join(lines), KB(inline_keyboard=kb))


def speakers(hub, pid: int) -> list[str]:
    s = hub.scripts.approved(pid) or hub.scripts.latest(pid)
    return parser.parse(s["content"]).characters if s else []


async def voices(target, hub, pid: int) -> None:
    from app.audio import tts as T
    from app.core.errors import HubError

    lang = hub.projects.get_project(pid)["settings"].get("language", "hindi")
    roles = speakers(hub, pid)
    cast = hub.library.casting(pid)
    hints = {r: hub.library.get(cast[r]["item_id"], cast[r]["version"])["profile"] for r in roles if r in cast}
    vmap = T.assign(hub.db, pid, roles, hints)
    try:
        base = hub.tts.check(lang)
        head = f"Awaaz engine: Piper ({base}) — laptop par, free, bina internet ke."
        ok = True
    except HubError as e:
        head, ok = "❌ " + e.user_message, False
    lines = ["🎤 Step 3: Awaaz", "", head, "Ek hi awaaz se har character ki alag awaaz (pitch + speed badal ke):", ""]
    kb: list[list[B]] = []
    for i, r in enumerate(roles[:12]):
        st = T.STYLES[vmap.get(r, 0) % len(T.STYLES)]
        lines.append(f"🧍 {r}: {st.name}")
        row = [B(text=f"🔄 {r[:14]}", callback_data=make("w", "vstyle", pid, i))]
        if ok:
            row.append(B(text="🔊 Suno", callback_data=make("w", "vsample", pid, i)))
        kb.append(row)
    lines.append(f"📖 Narrator: {T.NARRATOR.name}")
    kb.append([B(text="✅ Awaaz theek, aage ▶", callback_data=make("w", "check", pid))] if ok else
              [B(text="🔄 Dobara check karo", callback_data=make("w", "voice", pid))])
    kb.append(nav(back=f"w|chars|{pid}", refresh=f"w|voice|{pid}"))
    await show(target, "\n".join(lines), KB(inline_keyboard=kb))


async def _voice_sample(cb: CallbackQuery, hub, pid: int, idx: int) -> None:
    import asyncio
    import tempfile

    from aiogram.types import FSInputFile

    from app.audio import tts as T
    from app.observability.diagnostics import find_ffmpeg

    roles = speakers(hub, pid)
    if idx >= len(roles):
        raise ValueError("stale")
    role = roles[idx]
    lang = hub.projects.get_project(pid)["settings"].get("language", "hindi")
    voice = hub.tts.check(lang)
    s = hub.scripts.approved(pid) or hub.scripts.latest(pid)
    line = next((ln.text for sc in parser.parse(s["content"]).scenes for ln in sc.lines if ln.kind == "dialogue" and ln.speaker == role),
                "नमस्ते!" if lang != "english" else "Hello!")
    ffmpeg = find_ffmpeg(hub.settings)
    with tempfile.TemporaryDirectory() as td:
        raw, done, ogg = Path(td) / "r.wav", Path(td) / "d.wav", Path(td) / "v.ogg"

        def work() -> None:
            import subprocess

            hub.tts.synth(line[:200], voice, raw)
            T.apply_style(ffmpeg, raw, done, T.style_of(T.voice_map(hub.db, pid), role))
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(done), "-c:a", "libopus", "-b:a", "48k", str(ogg)],
                           capture_output=True, timeout=60)

        await asyncio.to_thread(work)
        m = _m(cb)
        if m and ogg.exists():
            await m.answer_voice(FSInputFile(ogg), caption=f"{role}: {line[:80]}", parse_mode=None)


async def final_check(target, hub, pid: int) -> None:
    from app.animation.two_d import jobs as anim_jobs

    p = hub.projects.get_project(pid)
    s = hub.scripts.approved(pid)
    scenes = hub.storyboards.scenes(pid)
    sb = hub.storyboards.state(pid)
    miss = missing_pictures(hub, pid)
    busy = [j for j in hub.jobs.list_jobs(active_only=True, project_id=pid, limit=20) if j["job_type"] == "storyboard_draft"]
    lines = [f"✅ Step 4: Final check — {p['name']}", "",
             f"1. Kahani: {'✅ v' + str(s['version_number']) if s else '❌ approve nahi'}",
             f"2. Scenes: " + ("⏳ ban rahe hain…" if busy else f"✅ {len(scenes)} scenes · ~{sum(x['duration_seconds'] for x in scenes):.0f}s"
                               + (" (approved)" if sb.get("status") == "approved" else "") if scenes else "❌ abhi nahi bane"),
             f"3. Characters & jagah: {'✅ sabki image hai' if not miss else '❌ ' + str(len(miss)) + ' ki image nahi'}",
             f"4. Awaaz: {_voice_status(hub, p)}",
             f"5. Size: {p['settings'].get('aspect')} · {p['settings'].get('resolution')} · {p['settings'].get('fps')}fps"]
    kb: list[list[B]] = []
    if scenes:
        kb.append([B(text="🎞 Scenes dekho", callback_data=make("sb", "sc", pid, 0)),
                   B(text="🖼 Pehla scene (photo)", callback_data=make("an", "still", pid))])
    if not scenes and not busy and s:
        kb.append([B(text="🎞 Scenes banao", callback_data=make("w", "sbdraft", pid))])
    if s and scenes and not miss and not busy:
        kb.append([B(text="🎬 Sab sahi — Final video banao", callback_data=make("w", "final", pid))])
    done = anim_jobs.exports(hub, pid, 1)
    if done:
        kb.append([B(text="📤 Bani videos", callback_data=make("an", "out", pid))])
    kb.append(nav(back=f"w|chars|{pid}", refresh=f"w|check|{pid}"))
    await show(target, "\n".join(lines), KB(inline_keyboard=kb))


def _voice_status(hub, p: dict) -> str:
    from app.core.errors import HubError

    try:
        return f"✅ {hub.tts.check(p['settings'].get('language', 'hindi'))} (har character ki alag pitch/speed)"
    except HubError:
        return "❌ Piper / awaaz file nahi mili — Step 3 me fix ke steps"


async def go_next(target, hub, pid: int) -> None:
    st = next_step(hub, pid)
    if st == "start":
        await story_input(target, hub)
    elif st == "story":
        await story_review(target, hub, pid)
    elif st == "chars":
        await chars(target, hub, pid)
    else:
        await final_check(target, hub, pid)


# ------------------------------------------------------------------ helpers
def _new_project(hub, name: str = PLACEHOLDER, seconds: int | None = None) -> int:
    settings = {"target_seconds": seconds} if seconds else None
    p = hub.projects.create_project(name, "2d", settings)
    hub.audit.record("project_create", "ok", "project", p["id"], via="wizard")
    return p["id"]


def _title_name(hub, pid: int) -> None:
    """Name the project after the story title (only if it still has the placeholder name)."""
    s = hub.scripts.latest(pid)
    p = hub.projects.get_project(pid)
    if s and p["name"].startswith(PLACEHOLDER):
        title = parser.parse(s["content"]).title.strip()
        if len(title) >= 2:
            hub.projects.update_project(pid, {"name": title[:80]})


def _looks_like_script(text: str) -> bool:
    ps = parser.parse(text)
    return bool(ps.characters) and any(ln.kind == "dialogue" for sc in ps.scenes for ln in sc.lines)


async def _story_received(message: Message, hub, text: str) -> None:
    uid = message.from_user.id if message.from_user else 0
    hub.extra["conv"].clear(uid)
    first = " ".join(text.split()[:5])[:40] or PLACEHOLDER
    title = parser.parse(text).title.strip() if text.lstrip().lower().startswith("title") else ""
    pid = _new_project(hub, title or first)
    if _looks_like_script(text) or not await hub.llm.available():
        hub.scripts.create_version(pid, text)
        if not _looks_like_script(text):
            await message.answer("ℹ️ AI band hai, isliye kahani narrator ki awaaz me rahegi (characters ke dialogue nahi bane). "
                                 "Settings me Cloud AI ON karke 🔁 AI se badlaav kar sakte ho.", parse_mode=None)
        await story_review(message, hub, pid)
        return
    job = hub.jobs.submit_job("script_write", pid, {"project_id": pid, "story": text[:12000], "wizard": True}, 3,
                              idempotency_key=f"wz:story:{uid}:{message.message_id}", chat_id=message.chat.id,
                              title="Kahani → script (AI)")
    from app.telegram.handlers.jobs import send_card

    await message.answer("📖 Kahani mil gayi! AI isme characters aur dialogue bana raha hai… ban jaane par main khud agla step bhejunga.",
                         parse_mode=None)
    await send_card(message, hub, job["id"])


# ------------------------------------------------------------------ callbacks
@router.callback_query(F.data.func(lambda d: (c := parse(d)) is not None and c.area == "w"))
async def cb_wizard(cb: CallbackQuery, hub) -> None:
    c = parse(cb.data)
    assert c is not None
    conv = hub.extra["conv"]
    uid = cb.from_user.id
    try:
        a = c.action
        if a == "start":
            await answer(cb)
            await start(cb, hub)
        elif a == "type":
            if c.arg() != "2d":
                raise ValueError("type")
            await answer(cb)
            await story_input(cb, hub)
        elif a in ("paste", "file"):
            conv.set(uid, "wz_story")
            await answer(cb)
            await show(cb, "📋 Apni kahani yahan paste karke bhejo." if a == "paste" else "📄 Kahani ki file bhejo (PDF, Word .docx ya .txt).",
                       KB(inline_keyboard=[nav(back="w|type|2d", cancel=True)]))
        elif a == "ai":
            if not await hub.llm.available():
                await answer(cb, "AI band hai: Ollama chalao ya ⚙️ Settings me Cloud AI ON karo", alert=True)
                return
            await answer(cb)
            kb = [[B(text=v, callback_data=make("w", "genre", k))] for k, v in GENRES.items()]
            kb.append(nav(back="w|type|2d"))
            await show(cb, "🤖 AI kahani — kis type ki?", KB(inline_keyboard=kb))
        elif a == "genre":
            g = c.arg()
            if g not in GENRES:
                raise ValueError("genre")
            await answer(cb)
            kb = [[B(text=f"⏱ {s}s" if s < 60 else f"⏱ {s // 60} min", callback_data=make("w", "len", g, s)) for s in LENGTHS],
                  nav(back="w|ai")]
            await show(cb, f"{GENRES[g]}\n\nVideo kitni lambi?", KB(inline_keyboard=kb))
        elif a == "len":
            g, secs = c.arg(0), c.int(1)
            if g not in GENRES or secs not in LENGTHS:
                raise ValueError("len")
            conv.set(uid, "wz_idea", genre=g, seconds=secs)
            await answer(cb)
            await show(cb, f"💡 Apna idea 1-2 line me likho (jaise: 'Golu khargosh jo sabse tez daudna chahta hai').\n"
                           "Ya AI ko khud sochne do:",
                       KB(inline_keyboard=[[B(text="⏭ AI khud soche", callback_data=make("w", "noidea"))], nav(back=f"w|genre|{g}", cancel=True)]))
        elif a == "noidea":
            st = conv.get(uid)
            if not st or st["step"] != "wz_idea":
                raise ValueError("stale")
            m = _m(cb)
            await answer(cb)
            if m:
                await _ai_story(m, hub, uid, st["data"], "")
        elif a == "story":
            await answer(cb)
            await story_review(cb, hub, c.int(0))
        elif a == "okstory":
            pid, sid = c.int(0), c.int(1)
            s = hub.scripts.get(sid)
            if s["project_id"] != pid:
                raise ValueError("stale")
            if s["approval_status"] != "approved":
                hub.scripts.approve(sid)
                hub.audit.record("script_approve", "ok", "script", sid, project=pid, via="wizard")
            _title_name(hub, pid)
            if not hub.storyboards.scenes(pid) or hub.storyboards.state(pid).get("script_id") != sid:
                m = _m(cb)
                hub.jobs.submit_job("storyboard_draft", pid, {"project_id": pid, "use_ai": True, "replace": True, "wizard": True}, 3,
                                    idempotency_key=f"wz:sb:{pid}:{sid}", chat_id=m.chat.id if m else None, title="Scenes (storyboard)")
            await answer(cb, "Kahani pakki! Scenes peeche ban rahe hain")
            await chars(cb, hub, pid)
        elif a == "chars":
            await answer(cb)
            await chars(cb, hub, c.int(0))
        elif a == "photos":
            pid = c.int(0)
            await answer(cb, "Photos bhej raha hoon…")
            await _send_photos(cb, hub, pid)
        elif a in ("aiall", "redo", "redo_ok"):
            from app.telegram.handlers.library import missing_images

            pid = c.int(0)
            if a == "redo":
                await answer(cb)
                await show(cb, "🔁 Is kahani ke saare characters aur jagah ki image dobara banegi (AI pehle unka sahi angrezi "
                               "description likhega, jaise लोमड़ी = fox). Purani image version history me rahegi. Pakka?",
                           KB(inline_keyboard=[[B(text="✅ Haan, dobara banao", callback_data=make("w", "redo_ok", pid))], nav(back=f"w|chars|{pid}")]))
                return
            if a == "redo_ok":
                todo = {r: row for r, row in hub.library.casting(pid).items()}
            else:
                todo = missing_images(hub, pid)
            if not todo:
                await answer(cb, "Sabki image pehle se hai")
                await chars(cb, hub, pid)
                return
            if not await hub.imagegen.available():
                await answer(cb, "Image AI band hai: ⚙️ Settings me Cloud AI ON karo (keys.txt me Cloudflare key)", alert=True)
                return
            m = _m(cb)
            for role, row in todo.items():
                hub.jobs.submit_job("library_ai_image", None,
                                    {"item_id": row["item_id"], "recast": {"project_id": pid, "role": role}, "wizard": pid,
                                     "redescribe": a == "redo_ok"}, 4,
                                    idempotency_key=f"wz:img:{pid}:{row['item_id']}:{m.message_id if m else 0}",
                                    chat_id=m.chat.id if m else None, title=f"AI image: {role[:30]}")
            await answer(cb, f"{len(todo)} images ban rahi hain")
            await show(cb, f"🎨 {len(todo)} images ek-ek karke ban rahi hain (har ek ~20-60 sec).\nSab ban jaane par main khud batata hoon.",
                       KB(inline_keyboard=[nav(back=f"w|chars|{pid}", refresh=f"w|chars|{pid}")]))
        elif a == "voice":
            await answer(cb)
            await voices(cb, hub, c.int(0))
        elif a == "vstyle":
            from app.audio import tts as T

            pid, idx = c.int(0), c.int(1)
            roles = speakers(hub, pid)
            if idx >= len(roles):
                raise ValueError("stale")
            cur = T.voice_map(hub.db, pid).get(roles[idx], 0)
            T.set_style(hub.db, pid, roles[idx], cur + 1)
            await answer(cb, f"{roles[idx]}: {T.STYLES[(cur + 1) % len(T.STYLES)].name}")
            await voices(cb, hub, pid)
        elif a == "vsample":
            await answer(cb, "Awaaz bana raha hoon…")
            await _voice_sample(cb, hub, c.int(0), c.int(1))
        elif a == "check":
            await answer(cb)
            await final_check(cb, hub, c.int(0))
        elif a == "sbdraft":
            pid = c.int(0)
            m = _m(cb)
            hub.jobs.submit_job("storyboard_draft", pid, {"project_id": pid, "use_ai": True, "replace": True, "wizard": True}, 3,
                                idempotency_key=f"wz:sb2:{pid}:{m.message_id if m else 0}", chat_id=m.chat.id if m else None,
                                title="Scenes (storyboard)")
            await answer(cb, "Scenes ban rahe hain")
            await final_check(cb, hub, pid)
        elif a == "final":
            from app.animation.two_d import jobs as anim_jobs

            pid = c.int(0)
            if hub.storyboards.state(pid).get("status") != "approved":
                hub.storyboards.approve(pid)
                hub.audit.record("storyboard_approve", "ok", "project", pid, via="wizard_final_check")
            m = _m(cb)
            job = anim_jobs.start(hub, pid, "final", chat_id=m.chat.id if m else None,
                                  key=f"wz:final:{pid}:{m.message_id if m else 0}")
            await answer(cb, "Final video ban rahi hai")
            if m:
                from app.telegram.handlers.jobs import send_card

                await m.answer("🎬 Final video ban rahi hai. Ban jaate hi yahin bhej dunga.", parse_mode=None)
                await send_card(m, hub, job["id"])
        elif a == "next":
            await answer(cb)
            await go_next(cb, hub, c.int(0))
        else:
            await answer(cb, "Ye button purana ho gaya.", alert=True)
    except ValueError:
        await answer(cb, "Ye button purana ho gaya.", alert=True)
    except Exception as e:  # noqa: BLE001
        await fail(cb, e)


async def _ai_story(message: Message, hub, uid: int, data: dict, idea: str) -> None:
    hub.extra["conv"].clear(uid)
    g, secs = data.get("genre", "seekh"), int(data.get("seconds", 60))
    text = f"{GENRE_IDEA.get(g, '')}. {idea}".strip()
    if not idea:
        text += ". Invent fresh characters and a fresh plot."
    pid = _new_project(hub, f"{PLACEHOLDER} {time.strftime('%d-%m %H:%M')}", secs)
    job = hub.jobs.submit_job("script_write", pid, {"project_id": pid, "text": text[:800], "wizard": True}, 3,
                              idempotency_key=f"wz:ai:{uid}:{message.message_id}", chat_id=message.chat.id, title="AI kahani")
    from app.telegram.handlers.jobs import send_card

    await message.answer("🤖 AI kahani likh raha hai… ban jaate hi main khud agla step bhejunga.", parse_mode=None)
    await send_card(message, hub, job["id"])


async def _send_photos(cb: CallbackQuery, hub, pid: int) -> None:
    from app.characters import imaging
    from app.telegram.handlers.library import project_roles

    m = _m(cb)
    if not m:
        return
    cast = hub.library.casting(pid)
    media = []
    for _k, role in project_roles(hub, pid):
        c = cast.get(role)
        if not c:
            continue
        it = hub.library.get(c["item_id"], c["version"])
        path = hub.library.file_path(it, "background" if it["kind"] == "environment" else "main")
        if path:
            data = imaging.preview(imaging.open_image(path.read_bytes()))
            media.append(InputMediaPhoto(media=BufferedInputFile(data, f"{len(media)}.jpg"), caption=f"{role} → {it['name']}"[:200]))
    if not media:
        await m.answer("Abhi kisi ki image nahi hai. 🎨 AI image banao.", parse_mode=None)
        return
    for i in range(0, len(media), 10):
        await m.answer_media_group(media[i:i + 10])


# ------------------------------------------------------------------ text / file replies
async def on_text(message: Message, hub, step: str, data: dict) -> bool:
    text = (message.text or "").strip()
    if step == "wz_story":
        if len(text) < 20:
            await message.answer("Kahani thodi aur lambi bhejo (kam se kam 2-3 line).", parse_mode=None)
            return True
        await _story_received(message, hub, text)
        return True
    if step == "wz_idea":
        await _ai_story(message, hub, message.from_user.id if message.from_user else 0, data, text[:500])
        return True
    return False


async def on_media(message: Message, hub, step: str, data: dict) -> bool:
    if step != "wz_story" or not message.document:
        return False
    from app.scripts.inputs import read_text_file

    doc = message.document
    suffix = Path(doc.file_name or "").suffix.lower()
    name = check_upload("document" if suffix in (".pdf", ".docx") else "text", doc.file_name or "kahani.txt", doc.file_size or 0)
    folder = hub.settings.data_dir / "work" / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{int(time.time())}_{name}"
    await message.bot.download(doc, destination=dest)
    text = read_text_file(dest)
    await _story_received(message, hub, text)
    return True


# ------------------------------------------------------------------ job events -> next screen
class WizardNotifier:
    """When a wizard job finishes, send the next step's screen so the owner never has to hunt for it."""

    def __init__(self, hub) -> None:
        self.hub = hub

    async def __call__(self, topic: str, data: dict) -> None:
        from app.scheduler import service as S
        from app.storage.db import loads

        if data.get("status") != S.COMPLETED or self.hub.bot is None:
            return
        job = self.hub.jobs.get_job(data["job_id"])
        inputs = loads(job["input_manifest"], {}) or {}
        if not inputs.get("wizard") or not job["chat_id"]:
            return

        class _T:
            def __init__(self, bot, chat_id):
                self.bot, self.chat_id = bot, chat_id

            async def answer(self, text, **kw):
                return await self.bot.send_message(self.chat_id, text, **kw)

        t = _T(self.hub.bot, job["chat_id"])
        try:
            if job["job_type"] == "script_write":
                pid = int(inputs["project_id"])
                _title_name(self.hub, pid)
                await story_review(t, self.hub, pid)  # type: ignore[arg-type]
            elif job["job_type"] == "library_ai_image":
                pid = int(inputs["wizard"])
                waiting = [j for j in self.hub.jobs.list_jobs(active_only=True, limit=50) if j["job_type"] == "library_ai_image"]
                if not waiting:
                    await chars(t, self.hub, pid)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            from app.observability.log import get_logger

            get_logger(__name__).exception("wizard_notify_failed")
