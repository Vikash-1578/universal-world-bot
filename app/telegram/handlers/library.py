"""Character Studio + Environment Studio + project casting (Milestone 5).

Callback area "lb". kind codes: c = character, e = environment, p = prop.
"""
from __future__ import annotations

import io
import time

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Message

from app.characters import packages, templates
from app.characters.service import EXPRESSIONS, POSES
from app.scripts import parser
from app.storage.files import check_upload
from app.telegram.callbacks.codec import make, parse
from app.telegram.keyboards.menus import confirm, nav, pager
from app.telegram.ui import ago, answer, fail, show

router = Router(name="library")
K = {"c": "character", "e": "environment", "p": "prop"}
KC = {v: k for k, v in K.items()}
TITLE = {"c": "🧍 Character Studio", "e": "🏞 Environment Studio", "p": "🧸 Props"}
TKIND = {"c": "actor", "e": "place"}
QC_ICON = {"unchecked": "⬜ check baaki", "needs_fix": "⚠️ theek karna hai", "ok": "🟢 QC ok", "approved": "✅ approved"}
PER = 7


def _m(target) -> Message | None:
    if isinstance(target, CallbackQuery):
        return target.message if isinstance(target.message, Message) else None
    return target


# ------------------------------------------------------------------ screens
async def home(target, hub, k: str) -> None:
    kind = K[k]
    _, own = hub.library.list_items(kind, limit=1)
    n_t = len(templates.entries(kind=TKIND[k])) if k in TKIND else 0
    img_ok = await hub.imagegen.available()
    text = (f"{TITLE[k]}\n\nTumhari library: {own}\nReady templates: {n_t}\n"
            f"🎨 AI image (ComfyUI): {'chalu' if img_ok else 'band — apni image upload karo'}")
    rows = [[B(text=f"📂 Meri library ({own})", callback_data=make("lb", "list", k, 0))],
            [B(text="➕ Naya banao", callback_data=make("lb", "new", k))]]
    if n_t:
        rows.append([B(text=f"📚 Templates ({n_t})", callback_data=make("lb", "tcat", k)),
                     B(text="🔍 Dhoondho", callback_data=make("lb", "find", k))])
    rows.append([B(text="📦 Package import", callback_data=make("lb", "imp", k))])
    if k == "c":
        rows.append([B(text="🧸 Props", callback_data=make("lb", "home", "p"))])
    rows.append(nav())
    await show(target, text, KB(inline_keyboard=rows))


async def item_list(target, hub, k: str, page: int, query: str = "") -> None:
    rows, total = hub.library.list_items(K[k], query=query, offset=page * PER, limit=PER)
    kb = [[B(text=f"{r['name'][:30]} · {QC_ICON.get(r['qc_status'], '')[:12]}", callback_data=make("lb", "open", r["id"]))] for r in rows]
    if total > PER:
        kb.append(pager("lb", "list", page, total, PER, k))
    kb.append([B(text="➕ Naya", callback_data=make("lb", "new", k))])
    kb.append(nav(back=f"lb|home|{k}"))
    await show(target, f"📂 {TITLE[k]} — library ({total})" + ("" if rows else "\n\nAbhi khali hai. ➕ Naya ya 📚 Templates se banao."),
               KB(inline_keyboard=kb))


def item_text(hub, it: dict) -> str:
    p = it["profile"]
    files = it["files"]
    lines = [f"{'🧍' if it['kind'] == 'character' else '🏞' if it['kind'] == 'environment' else '🧸'} {it['name']}  ({it['id']})",
             f"Version v{it['version']} · {QC_ICON.get(it['qc_status'], it['qc_status'])}" + (f" · {it['category']}" if it["category"] else "")]
    if p.get("description"):
        lines.append(f"📝 {p['description'][:300]}")
    if p.get("look") and p.get("look") != p.get("description"):
        lines.append(f"🎨 Look: {p['look'][:300]}")
    if it["kind"] == "character":
        if p.get("voice"):
            v = p["voice"]
            lines.append(f"🎤 Awaaz: {v.get('preset', '-')} (Milestone 8 me sunai degi)")
        exprs = [r.split(":")[1] for r in files if r.startswith("expr:") and not r.endswith(":original")]
        poses = [r.split(":")[1] for r in files if r.startswith("pose:") and not r.endswith(":original")]
        lines.append(f"🖼 Main image: {'✅' if 'main' in files else '❌ nahi'} · Expressions: {', '.join(exprs) or '-'} · Poses: {', '.join(poses) or '-'}")
    elif it["kind"] == "environment":
        lines.append(f"🖼 Background: {'✅' if 'background' in files else '❌ nahi'}" + (" · 🌙 raat wala ✅" if "background:night" in files else ""))
    main = "background" if it["kind"] == "environment" else "main"
    q = it["qc"].get(main)
    if q:
        lines.append(f"QC: {'✅ theek' if q.get('ok') else '⚠️ ' + '; '.join(q.get('problems', []))[:250]}")
        if it["kind"] == "character":
            lines.append(f"Rig: gardan {'✅' if q.get('neck_row') is not None else '❌'} · pair {'✅' if q.get('legs') else '❌'}")
    used = hub.library.used_by(it["id"])
    if used:
        lines.append("🔗 Projects: " + ", ".join(f"{u['name']} (v{u['version']})" for u in used[:4]))
    return "\n".join(lines)


async def item_card(target, hub, iid: str) -> None:
    it = hub.library.get(iid)
    k = KC[it["kind"]]
    main = "background" if it["kind"] == "environment" else "main"
    rows = [[B(text="🖼 Image bhejo" if main not in it["files"] else "🖼 Nayi image", callback_data=make("lb", "img", iid, main)),
             B(text="🎨 AI image", callback_data=make("lb", "aiimg", iid))]]
    if it["kind"] == "character":
        rows.append([B(text="😀 Expression", callback_data=make("lb", "exl", iid)), B(text="🧍 Pose", callback_data=make("lb", "pol", iid))])
    if it["kind"] == "environment":
        rows.append([B(text="🌙 Raat wali image", callback_data=make("lb", "img", iid, "background:night"))])
    rows += [[B(text="✏️ Description", callback_data=make("lb", "desc", iid)), B(text="✍️ AI description", callback_data=make("lb", "aidesc", iid))],
             [B(text="👁 Image dekho", callback_data=make("lb", "see", iid)), B(text="✅ QC approve", callback_data=make("lb", "qcok", iid))],
             [B(text="📦 Export", callback_data=make("lb", "exp", iid)), B(text="🕘 Versions", callback_data=make("lb", "vers", iid))],
             nav(back=f"lb|list|{k}|0", refresh=f"lb|open|{iid}")]
    await show(target, item_text(hub, it), KB(inline_keyboard=rows))


async def template_cats(target, k: str) -> None:
    cats = sorted(templates.categories(TKIND[k]), key=lambda c: -c[2])
    kb, row = [], []
    for key, label, n in cats:
        row.append(B(text=f"{label} ({n})"[:30], callback_data=make("lb", "tl", k, key[:20], 0)))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append(nav(back=f"lb|home|{k}"))
    await show(target, "📚 Templates — category chuno\n(Template sirf profile hai; image tum doge ya AI banayega.)", KB(inline_keyboard=kb))


async def template_list(target, k: str, cat: str, page: int) -> None:
    items = [t for t in templates.entries(kind=TKIND[k]) if t["category"][:20] == cat]
    chunk = items[page * PER:(page + 1) * PER]
    kb = [[B(text=t["name"][:40], callback_data=make("lb", "tv", t["id"]))] for t in chunk]
    if len(items) > PER:
        kb.append(pager("lb", "tl", page, len(items), PER, k, cat))
    kb.append(nav(back=f"lb|tcat|{k}"))
    await show(target, f"📚 {templates.catalog()['categories'].get(cat, cat)} ({len(items)})", KB(inline_keyboard=kb))


# ------------------------------------------------------------------ casting
def project_roles(hub, pid: int) -> list[tuple[str, str]]:
    """(kind, role name) for every character + place in the approved script, in order."""
    s = hub.scripts.approved(pid) or hub.scripts.latest(pid)
    if not s:
        return []
    ps = parser.parse(s["content"])
    roles = [("c", c) for c in ps.characters]
    seen = set()
    for sc in ps.scenes:
        place = (sc.heading.split(",")[0] if sc.heading else "").strip()
        if place and place not in seen:
            seen.add(place)
            roles.append(("e", place))
    return roles


async def cast_screen(target, hub, pid: int) -> None:
    p = hub.projects.get_project(pid)
    roles = project_roles(hub, pid)
    cast = hub.library.casting(pid)
    if not roles:
        await show(target, f"🎭 Casting — {p['name']}\n\nPehle Script Studio me script do.", KB(inline_keyboard=[nav(back=f"p|open|{pid}")]))
        return
    lines = [f"🎭 Casting — {p['name']}", "Script ke har character / jagah ko library ka item do:"]
    kb = []
    for i, (k, role) in enumerate(roles):
        c = cast.get(role)
        mark = f"✅ {c['name']} v{c['version']}" + (" (naya version hai)" if c and c["outdated"] else "") if c else "❌ khali"
        lines.append(f"{'🧍' if k == 'c' else '🏞'} {role}: {mark}")
        kb.append([B(text=f"{'🧍' if k == 'c' else '🏞'} {role[:24]}", callback_data=make("lb", "role", pid, i))])
    kb.append(nav(back=f"p|open|{pid}", refresh=f"lb|cast|{pid}"))
    await show(target, "\n".join(lines), KB(inline_keyboard=kb))


async def role_screen(target, hub, pid: int, idx: int) -> None:
    roles = project_roles(hub, pid)
    if idx >= len(roles):
        await cast_screen(target, hub, pid)
        return
    k, role = roles[idx]
    own, tmpl = hub.library.suggest_for(role, K[k])
    kb = [[B(text=f"📂 {o['name'][:30]}", callback_data=make("lb", "assign", pid, idx, o["id"]))] for o in own]
    kb += [[B(text=f"📚 {t['name'][:30]} (template)", callback_data=make("lb", "assignt", pid, idx, t["id"]))] for t in tmpl]
    kb.append([B(text=f"➕ '{role[:20]}' naya banao", callback_data=make("lb", "assignn", pid, idx))])
    cur = hub.library.casting(pid).get(role)
    if cur:
        kb.append([B(text="✖ Hatao", callback_data=make("lb", "unassign", pid, idx))])
        if cur["outdated"]:
            kb.append([B(text=f"⬆ Naye version v{cur['current_version']} par lao", callback_data=make("lb", "assign", pid, idx, cur["item_id"]))])
    kb.append(nav(back=f"lb|cast|{pid}"))
    await show(target, f"🎭 '{role}' ke liye {'character' if k == 'c' else 'jagah'} chuno:" +
               ("" if own or tmpl else "\n(Library/templates me match nahi mila — naya banao.)"), KB(inline_keyboard=kb))


# ------------------------------------------------------------------ callbacks
@router.callback_query(F.data.func(lambda d: (c := parse(d)) is not None and c.area == "lb"))
async def cb_library(cb: CallbackQuery, hub) -> None:
    c = parse(cb.data)
    assert c is not None
    lib = hub.library
    conv = hub.extra["conv"]
    uid = cb.from_user.id
    try:
        a = c.action
        if a == "home":
            await answer(cb)
            await home(cb, hub, c.arg(0) if c.arg(0) in K else "c")
        elif a == "list":
            await answer(cb)
            await item_list(cb, hub, c.arg(1) if c.arg(1) in K else c.arg(0), c.int(0) if c.arg(0).isdigit() else 0)
        elif a == "new":
            k = c.arg(0)
            conv.set(uid, "lib_new", kind=K[k])
            await answer(cb)
            await show(cb, f"➕ Naya {K[k]}: naam likho (jaise: {'Golu Khargosh' if k == 'c' else 'Jungle ka talab'}).\n"
                           "Naam ke baad ek line me description bhi likh sakte ho (Enter daba ke).",
                       KB(inline_keyboard=[nav(back=f"lb|home|{k}", cancel=True)]))
        elif a == "find":
            conv.set(uid, "lib_find", kind=K[c.arg(0)])
            await answer(cb)
            await show(cb, "🔍 Kya dhoondhna hai? (jaise: sher, doctor, school, raat)", KB(inline_keyboard=[nav(back=f"lb|home|{c.arg(0)}", cancel=True)]))
        elif a == "imp":
            conv.set(uid, "lib_pkg")
            await answer(cb)
            await show(cb, "📦 .uwpkg.zip package file bhejo (jo is bot ke Export se bani ho).", KB(inline_keyboard=[nav(cancel=True)]))
        elif a == "tcat":
            await answer(cb)
            await template_cats(cb, c.arg(0))
        elif a == "tl":
            await answer(cb)
            # pager sends (page, k, cat); category list sends (k, cat, page)
            if c.arg(0).isdigit():
                await template_list(cb, c.arg(1), c.arg(2), c.int(0))
            else:
                await template_list(cb, c.arg(0), c.arg(1), c.int(2))
        elif a == "tv":
            t = templates.get(c.arg(0))
            if not t:
                raise ValueError("bad template")
            await answer(cb)
            await show(cb, f"📚 {t['name']}\n{templates.catalog()['categories'].get(t['category'], t['category'])}\n\n🎨 {t.get('look', '')}\n"
                           + (f"🎤 Awaaz: {t.get('voice')}" if t["kind"] == "actor" else ""),
                       KB(inline_keyboard=[[B(text="✅ Isse library me banao", callback_data=make("lb", "use", t["id"]))],
                                           nav(back=f"lb|tl|{'e' if t['kind'] == 'place' else 'c'}|{t['category'][:20]}|0")]))
        elif a == "use":
            it = lib.from_template(c.arg(0))
            hub.audit.record("library_create", "ok", "item", it["id"], template=c.arg(0))
            await answer(cb, "Library me ban gaya")
            await item_card(cb, hub, it["id"])
        elif a == "open":
            await answer(cb)
            await item_card(cb, hub, c.arg(0))
        elif a == "img":
            iid, role = c.arg(0), c.arg(1)
            lib.get(iid)
            conv.set(uid, "lib_img", item_id=iid, role=role)
            await answer(cb)
            hint = ("Plain ya hara (green) background wali photo/drawing bhejo — bot background hata dega.\n"
                    "Behtar: transparent PNG 'File' ki tarah bhejo (photo compress ho jaati hai).") if not role.startswith("background") else \
                   "Background ki image bhejo (16:9, kam se kam 1280x720). 'File' ki tarah bhejoge to quality achhi rahegi."
            await show(cb, f"🖼 {role} image bhejo.\n{hint}", KB(inline_keyboard=[nav(back=f"lb|open|{iid}", cancel=True)]))
        elif a in ("exl", "pol"):
            iid = c.arg(0)
            opts = EXPRESSIONS if a == "exl" else POSES
            pre = "expr" if a == "exl" else "pose"
            kb, row = [], []
            for o in opts:
                row.append(B(text=o, callback_data=make("lb", "img", iid, f"{pre}:{o}")))
                if len(row) == 3:
                    kb.append(row)
                    row = []
            if row:
                kb.append(row)
            kb.append(nav(back=f"lb|open|{iid}"))
            await answer(cb)
            await show(cb, "Kaunsi " + ("expression" if a == "exl" else "pose") + " ki image doge?\n"
                           "(Same character, same size aur angle me ho to animation achha banega.)", KB(inline_keyboard=kb))
        elif a == "desc":
            iid = c.arg(0)
            lib.get(iid)
            conv.set(uid, "lib_desc", item_id=iid)
            await answer(cb)
            await show(cb, "✏️ Description likho (kaisa dikhta hai, kapde, rang, swabhav):", KB(inline_keyboard=[nav(back=f"lb|open|{iid}", cancel=True)]))
        elif a in ("aidesc", "aiimg"):
            iid = c.arg(0)
            lib.get(iid)
            if a == "aidesc" and not await hub.llm.available():
                await answer(cb, "AI band hai (Ollama chalu karo) — ✏️ Description se khud likho", alert=True)
                return
            if a == "aiimg" and not await hub.imagegen.available():
                await answer(cb)
                await show(cb, "🎨 Image AI (ComfyUI) abhi nahi mila.\n\n• ComfyUI install karke chalao aur ek SDXL checkpoint daalo "
                               "(docs/model-compatibility.md me steps)\n• Tab tak 🖼 Image bhejo se apni drawing/photo do",
                           KB(inline_keyboard=[nav(back=f"lb|open|{iid}")]))
                return
            m = _m(cb)
            jt = "library_describe" if a == "aidesc" else "library_ai_image"
            job = hub.jobs.submit_job(jt, None, {"item_id": iid}, 4, idempotency_key=f"{jt}:{iid}:{m.message_id if m else 0}",
                                      chat_id=m.chat.id if m else None)
            await answer(cb, "Job line me laga")
            if m:
                from app.telegram.handlers.jobs import send_card

                await send_card(m, hub, job["id"])
        elif a == "see":
            it = lib.get(c.arg(0))
            m = _m(cb)
            await answer(cb)
            sent = 0
            from app.characters import imaging

            for role in [r for r in it["files"] if not r.endswith(":original") and not r.startswith("reference")][:6]:
                path = lib.file_path(it, role)
                if path and m:
                    im = imaging.open_image(path.read_bytes())
                    await m.answer_photo(BufferedInputFile(imaging.preview(im), f"{role}.jpg"), caption=f"{it['name']} · {role}", parse_mode=None)
                    sent += 1
            if not sent and m:
                await m.answer("Abhi koi image nahi hai. 🖼 Image bhejo dabao.", parse_mode=None)
        elif a == "qcok":
            it = lib.get(c.arg(0))
            main = "background" if it["kind"] == "environment" else "main"
            q = it["qc"].get(main, {})
            if q and not q.get("ok") and c.arg(1) != "force":
                await answer(cb)
                await show(cb, "⚠️ QC me problem hai:\n• " + "\n• ".join(q.get("problems", [])) + "\n\nPhir bhi approve karna hai?",
                           confirm("lb", "qcok", it["id"], "force", no_back=f"lb|open|{it['id']}"))
                return
            lib.approve_qc(it["id"])
            hub.audit.record("library_qc_approve", "ok", "item", it["id"])
            await answer(cb, "Approved")
            await item_card(cb, hub, it["id"])
        elif a == "exp":
            name, data = packages.export_item(lib, c.arg(0))
            m = _m(cb)
            await answer(cb)
            if m:
                await m.answer_document(BufferedInputFile(data, name), caption="📦 Character package — dusre project/computer me 📦 Package import se lao.",
                                        parse_mode=None)
        elif a == "vers":
            iid = c.arg(0)
            vs = lib.versions(iid)[:10]
            await answer(cb)
            await show(cb, "🕘 Versions (naya upar)\n\n" + "\n".join(f"v{v['version']} · {ago(v['created_at'])} · {v['note']}" for v in vs),
                       KB(inline_keyboard=[nav(back=f"lb|open|{iid}")]))
        # ---- casting
        elif a == "cast":
            await answer(cb)
            await cast_screen(cb, hub, c.int(0))
        elif a == "role":
            await answer(cb)
            await role_screen(cb, hub, c.int(0), c.int(1))
        elif a in ("assign", "assignt", "assignn", "unassign"):
            pid, idx = c.int(0), c.int(1)
            roles = project_roles(hub, pid)
            if idx >= len(roles):
                raise ValueError("stale")
            k, role = roles[idx]
            if a == "unassign":
                lib.uncast(pid, role)
            else:
                if a == "assign":
                    iid = c.arg(2)
                elif a == "assignt":
                    iid = lib.from_template(c.arg(2))["id"]
                else:
                    iid = lib.create_item(K[k], role)["id"]
                lib.cast(pid, role, iid)
                hub.audit.record("cast", "ok", "project", pid, role=role, item=iid)
            await answer(cb, "Casting save")
            await cast_screen(cb, hub, pid)
        else:
            await answer(cb, "Ye button purana ho gaya.", alert=True)
    except (ValueError, KeyError):
        await answer(cb, "Ye button purana ho gaya.", alert=True)
    except Exception as e:  # noqa: BLE001
        await fail(cb, e)


# ------------------------------------------------------------------ conversation input
async def on_text(message: Message, hub, step: str, data: dict) -> bool:
    uid = message.from_user.id if message.from_user else 0
    conv = hub.extra["conv"]
    text = (message.text or "").strip()
    if step == "lib_new":
        name, _, desc = text.partition("\n")
        it = hub.library.create_item(data["kind"], name, {"description": desc.strip()} if desc.strip() else {})
        conv.clear(uid)
        hub.audit.record("library_create", "ok", "item", it["id"])
        await item_card(message, hub, it["id"])
        return True
    if step == "lib_desc":
        it = hub.library.update_profile(data["item_id"], {"description": text})
        conv.clear(uid)
        await item_card(message, hub, it["id"])
        return True
    if step == "lib_find":
        kind = data["kind"]
        k = KC[kind]
        own, _ = hub.library.list_items(kind, query=text, limit=6)
        tmpl = templates.search(text, TKIND.get(k), limit=8) if k in TKIND else []
        conv.clear(uid)
        kb = [[B(text=f"📂 {o['name'][:34]}", callback_data=make("lb", "open", o["id"]))] for o in own]
        kb += [[B(text=f"📚 {t['name'][:34]}", callback_data=make("lb", "tv", t["id"]))] for t in tmpl]
        kb.append(nav(back=f"lb|home|{k}"))
        await message.answer(f"🔍 '{text[:40]}' — {len(own)} library, {len(tmpl)} templates", reply_markup=KB(inline_keyboard=kb), parse_mode=None)
        return True
    return False


async def on_media(message: Message, hub, step: str, data: dict) -> bool:
    uid = message.from_user.id if message.from_user else 0
    if step == "lib_img":
        if message.photo:
            ph = message.photo[-1]
            check_upload("image", "photo.jpg", ph.file_size or 1)
            media = ph
        elif message.document:
            check_upload("image", message.document.file_name or "image.png", message.document.file_size or 0)
            media = message.document
        else:
            return False
        buf = io.BytesIO()
        await message.bot.download(media, destination=buf)
        it, qc = hub.library.add_image(data["item_id"], data["role"], buf.getvalue())
        hub.extra["conv"].clear(uid)
        from app.characters import imaging

        path = hub.library.file_path(it, data["role"])
        if path:
            await message.answer_photo(BufferedInputFile(imaging.preview(imaging.open_image(path.read_bytes())), "preview.jpg"),
                                       caption=f"✅ {data['role']} save (v{it['version']})\n" + (qc.text() if qc else ""), parse_mode=None)
        await item_card(message, hub, it["id"])
        return True
    if step == "lib_pkg" and message.document:
        doc = message.document
        if not (doc.file_name or "").lower().endswith(".zip"):
            await message.answer("⚠️ .zip package bhejo.", parse_mode=None)
            return True
        if (doc.file_size or 0) > packages.MAX_PKG:
            await message.answer("⚠️ Package bahut bada hai.", parse_mode=None)
            return True
        buf = io.BytesIO()
        await message.bot.download(doc, destination=buf)
        it = packages.import_package(hub.library, buf.getvalue())
        hub.extra["conv"].clear(uid)
        hub.audit.record("library_import", "ok", "item", it["id"])
        await message.answer("📦 Import ho gaya.", parse_mode=None)
        await item_card(message, hub, it["id"])
        return True
    return False
