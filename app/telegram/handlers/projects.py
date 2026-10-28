"""Projects screens: list (paged), open, create (guided), rename, settings, versions, archive."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Message

from app.projects.service import ASPECTS, TYPES
from app.telegram.callbacks.codec import make, parse
from app.telegram.keyboards.menus import confirm, nav, pager
from app.telegram.ui import ago, answer, fail, show

router = Router(name="projects")
PER = 6
TYPE_ICON = {"2d": "🎨", "3d": "🧊", "slideshow": "🖼"}


async def show_list(target, hub, page: int, archived: bool = False) -> None:
    rows, total = hub.projects.list_projects(archived=archived, offset=page * PER, limit=PER)
    title = "🗄 Archived projects" if archived else "📁 Projects"
    if not rows:
        text = f"{title}\n\nAbhi koi project nahi." + ("" if archived else " 🎬 New Production se banao.")
    else:
        text = f"{title} ({total})"
    kb = [[B(text=f"{TYPE_ICON.get(r['project_type'], '')} {r['name'][:28]} · {r['status']}", callback_data=make("p", "open", r["id"]))]
          for r in rows]
    if total > PER:
        kb.append(pager("p", "list", page, total, PER, "a" if archived else "n"))
    kb.append([B(text="🎬 Naya project", callback_data=make("m", "new")),
               B(text="📁 Active" if archived else "🗄 Archived", callback_data=make("p", "list", 0, "n" if archived else "a"))])
    kb.append(nav())
    await show(target, text, KB(inline_keyboard=kb))


def project_text(p: dict, versions: int) -> str:
    s = p["settings"]
    return (f"{TYPE_ICON.get(p['project_type'], '')} {p['name']}  (#{p['id']})\n"
            f"Type: {TYPES[p['project_type']]} · Status: {p['status']}\n"
            f"Language: {s.get('language')} · Aspect: {s.get('aspect')} · {s.get('resolution')} {s.get('fps')}fps\n"
            f"Audience: {s.get('audience')} · Length ~{s.get('target_seconds')}s\n"
            f"Versions saved: {versions} · Updated {ago(p['updated_at'])}"
            + ("\n🗄 Archived" if p.get("archived_at") else ""))


async def show_project(target, hub, pid: int) -> None:
    p = hub.projects.get_project(pid)
    n = len(hub.projects.versions(pid))
    rows = [
        [B(text="📜 Script", callback_data=make("m", "script")), B(text="🎞 Storyboard", callback_data=make("m", "storyboard"))],
        [B(text="⚙️ Settings", callback_data=make("p", "set", pid)), B(text="✏️ Naam badlo", callback_data=make("p", "rename", pid))],
        [B(text="💾 Version save", callback_data=make("p", "save", pid)), B(text="🕘 Versions", callback_data=make("p", "vers", pid))],
        [B(text="⏳ Is project ke jobs", callback_data=make("j", "list", 0, pid))],
        [B(text="♻️ Wapas active" if p.get("archived_at") else "🗄 Archive", callback_data=make("p", "unarch" if p.get("archived_at") else "arch", pid))],
        nav(back="m|projects", refresh=f"p|open|{pid}"),
    ]
    await show(target, project_text(p, n), KB(inline_keyboard=rows))


async def start_new(target, hub) -> None:
    kb = [[B(text=f"{TYPE_ICON[k]} {v}", callback_data=make("p", "type", k))] for k, v in TYPES.items()]
    kb.append(nav(cancel=True))
    await show(target, "🎬 New Production\n\nKis tarah ka video?\n"
                       "• 2D cartoon — characters, awaaz, lip-sync (Milestone 6)\n"
                       "• 3D — Blender scene/render (Milestone 7)\n"
                       "• Images + narration — photos par awaaz aur subtitles", KB(inline_keyboard=kb))


def settings_kb(p: dict) -> KB:
    s, pid = p["settings"], p["id"]

    def mark(cond: bool, label: str) -> str:
        return ("✅ " if cond else "") + label

    return KB(inline_keyboard=[
        [B(text=mark(s.get("aspect") == a, a), callback_data=make("p", "opt", pid, "aspect", a.replace(":", "x"))) for a in ASPECTS],
        [B(text=mark(s.get("language") == l, lab), callback_data=make("p", "opt", pid, "language", l))
         for l, lab in (("hindi", "हिंदी"), ("english", "English"), ("hinglish", "Hinglish"))],
        [B(text=mark(s.get("fps") == f, f"{f} fps"), callback_data=make("p", "opt", pid, "fps", f)) for f in (24, 30)],
        [B(text=mark(s.get("target_seconds") == t, f"{t}s"), callback_data=make("p", "opt", pid, "target_seconds", t))
         for t in (30, 60, 120, 300)],
        [B(text=mark(s.get("audience") == a, lab), callback_data=make("p", "opt", pid, "audience", a))
         for a, lab in (("kids", "👶 Kids"), ("general", "👪 Sab"), ("adult", "🧑 Adult"))],
        nav(back=f"p|open|{pid}"),
    ])


@router.callback_query(F.data.func(lambda d: (c := parse(d)) is not None and c.area == "p"))
async def cb_projects(cb: CallbackQuery, hub) -> None:
    c = parse(cb.data)
    assert c is not None
    conv = hub.extra["conv"]
    try:
        a = c.action
        if a == "list":
            await answer(cb)
            await show_list(cb, hub, c.int(0), c.arg(1) == "a")
        elif a == "open":
            await answer(cb)
            await show_project(cb, hub, c.int(0))
        elif a == "type":
            if c.arg() not in TYPES:
                raise ValueError("bad type")
            conv.set(cb.from_user.id, "new_project_name", project_type=c.arg())
            await answer(cb)
            await show(cb, f"{TYPE_ICON[c.arg()]} {TYPES[c.arg()]}\n\nAb project ka naam likh ke bhejo (jaise: Kachhua Khargosh Race).",
                       KB(inline_keyboard=[nav(back="m|new", cancel=True)]))
        elif a == "rename":
            hub.projects.get_project(c.int(0))
            conv.set(cb.from_user.id, "rename_project", project_id=c.int(0))
            await answer(cb)
            await show(cb, "✏️ Naya naam likh ke bhejo.", KB(inline_keyboard=[nav(back=f"p|open|{c.int(0)}", cancel=True)]))
        elif a == "set":
            await answer(cb)
            p = hub.projects.get_project(c.int(0))
            await show(cb, "⚙️ Project settings\n\n" + project_text(p, len(hub.projects.versions(p["id"]))), settings_kb(p))
        elif a == "opt":
            pid, field, val = c.int(0), c.arg(1), c.arg(2)
            value: object = val.replace("x", ":") if field == "aspect" else int(val) if field in ("fps", "target_seconds") else val
            p = hub.projects.update_project(pid, {"settings": {field: value}})
            await answer(cb, "Save ho gaya")
            await show(cb, "⚙️ Project settings\n\n" + project_text(p, len(hub.projects.versions(pid))), settings_kb(p))
        elif a == "save":
            v = hub.projects.save_version(c.int(0), "Owner ne save kiya")
            hub.audit.record("project_version", "ok", "project", c.int(0), version=v["version_number"])
            await answer(cb, f"Version {v['version_number']} save ho gaya")
            await show_project(cb, hub, c.int(0))
        elif a == "vers":
            pid = c.int(0)
            vs = hub.projects.versions(pid)[:10]
            lines = [f"🕘 Versions — project #{pid}", ""]
            for v in vs:
                ok = "✅" if hub.projects.verify_version(v["id"]) else "⚠️ checksum mismatch"
                lines.append(f"v{v['version_number']} · {ago(v['created_at'])} · {v['description'] or '-'} {ok}")
            await answer(cb)
            await show(cb, "\n".join(lines), KB(inline_keyboard=[nav(back=f"p|open|{pid}")]))
        elif a == "arch":
            await answer(cb)
            await show(cb, "🗄 Project archive karna hai? (Kuch delete nahi hoga, baad me wapas la sakte ho.)",
                       confirm("p", "arch_ok", c.int(0), no_back=f"p|open|{c.int(0)}"))
        elif a == "arch_ok":
            hub.projects.archive_project(c.int(0))
            hub.audit.record("project_archive", "ok", "project", c.int(0))
            await answer(cb, "Archive ho gaya")
            await show_list(cb, hub, 0)
        elif a == "unarch":
            hub.projects.unarchive_project(c.int(0))
            await answer(cb, "Wapas active")
            await show_project(cb, hub, c.int(0))
        else:
            await answer(cb, "Ye button purana ho gaya.", alert=True)
    except ValueError:
        await answer(cb, "Ye button purana ho gaya.", alert=True)
    except Exception as e:  # noqa: BLE001
        await fail(cb, e)


async def on_text(message: Message, hub, step: str, data: dict) -> bool:
    """Called by the conversation router. Returns True if handled."""
    uid = message.from_user.id if message.from_user else 0
    text = (message.text or "").strip()
    if step == "new_project_name":
        p = hub.projects.create_project(text, data.get("project_type", "2d"))
        hub.extra["conv"].clear(uid)
        hub.audit.record("project_create", "ok", "project", p["id"])
        await message.answer("✅ Project ban gaya!", parse_mode=None)
        await show_project(message, hub, p["id"])
        return True
    if step == "rename_project":
        p = hub.projects.update_project(int(data["project_id"]), {"name": text})
        hub.extra["conv"].clear(uid)
        await show_project(message, hub, p["id"])
        return True
    return False
