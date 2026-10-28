"""🎭 Animation + 📤 Render & Export screens (Milestone 6). Callback area "an".

an|pick|page          choose a project
an|open|pid           plan summary: scenes, casting gaps, buttons
an|still|pid          one picture of scene 1 (fast check, no job)
an|go|pid|preview|final   start a render job
an|out|pid            finished videos of the project
an|send|asset_id      send one finished video
"""
from __future__ import annotations

import asyncio
import io

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Message

from app.animation.two_d import jobs as anim_jobs
from app.animation.two_d import planner
from app.core.errors import HubError
from app.scheduler import service as S
from app.storage.db import loads
from app.telegram.callbacks.codec import make, parse
from app.telegram.keyboards.menus import nav, pager
from app.telegram.ui import ago, answer, fail, show

router = Router(name="animation")
PER = 6
TG_LIMIT = 48 * 1024 * 1024  # bots can upload up to 50 MB


def _m(target) -> Message | None:
    if isinstance(target, CallbackQuery):
        return target.message if isinstance(target.message, Message) else None
    return target


async def pick(target, hub, page: int = 0) -> None:
    rows, total = hub.projects.list_projects(offset=page * PER, limit=PER)
    if not rows:
        await show(target, "🎭 Animation\n\nPehle ek project banao.", KB(inline_keyboard=[[B(text="🎬 Naya project", callback_data=make("m", "new"))], nav()]))
        return
    kb = [[B(text=f"{r['name'][:34]} · {r['status']}", callback_data=make("an", "open", r["id"]))] for r in rows]
    if total > PER:
        kb.append(pager("an", "pick", page, total, PER))
    kb.append(nav())
    await show(target, "🎭 Animation / 📤 Export\n\nKis project ki video banani hai?", KB(inline_keyboard=kb))


async def open_project(target, hub, pid: int) -> None:
    p = hub.projects.get_project(pid)
    back = [nav(back=f"p|open|{pid}", refresh=f"an|open|{pid}")]
    try:
        plan = planner.build(hub, pid, "preview")
    except HubError as e:
        await show(target, f"🎭 Animation — {p['name']}\n\n{e.user_message}", KB(inline_keyboard=back))
        return
    st = plan["storyboard_status"]
    lines = [f"🎭 Animation — {p['name']}",
             f"Storyboard: {'✅ approved' if st == 'approved' else '📝 draft (final ke liye approve karo)'}",
             f"Scenes: {len(plan['scenes'])} · lambai ~{plan['seconds']:.0f}s",
             f"Final size: {p['settings'].get('aspect')} · {p['settings'].get('resolution')} · {p['settings'].get('fps')}fps"]
    lines += ["", *plan["warnings"][:8]] if plan["warnings"] else ["", "✅ Sab characters aur jagah cast hain."]
    lines += ["", "ℹ️ Abhi video me awaaz nahi hai (khaali audio track). Awaaz + subtitles Milestone 8 me aayenge.",
              "Characters bolte waqt halke hilte hain; 'talk' expression image ho to munh bhi chalega."]
    done = anim_jobs.exports(hub, pid, 1)
    kb = [[B(text="🖼 Pehla scene dekho (photo)", callback_data=make("an", "still", pid))],
          [B(text="👀 Preview video (360p, jaldi)", callback_data=make("an", "go", pid, "preview"))],
          [B(text="🎬 Final video", callback_data=make("an", "go", pid, "final"))],
          [B(text=f"📤 Bani videos{' ✅' if done else ''}", callback_data=make("an", "out", pid))],
          [B(text="🎭 Casting", callback_data=make("lb", "cast", pid)), B(text="🎞 Storyboard", callback_data=make("sb", "open", pid))],
          *back]
    await show(target, "\n".join(lines), KB(inline_keyboard=kb))


async def outputs(target, hub, pid: int) -> None:
    rows = anim_jobs.exports(hub, pid)
    lines = [f"📤 Bani videos — project #{pid}"]
    kb = []
    if not rows:
        lines.append("\nAbhi koi video nahi bani. 🎭 Animation se preview banao.")
    for r in rows:
        m = r["meta"]
        ok = r["abs"].exists()
        lines.append(f"#{r['id']} {m.get('quality')} {m.get('width')}x{m.get('height')} · {m.get('seconds', 0):.0f}s · {ago(r['created_at'])}"
                     + ("" if ok else " ⚠️ file nahi mili"))
        if ok:
            kb.append([B(text=f"▶ #{r['id']} {m.get('quality')} bhejo", callback_data=make("an", "send", r["id"]))])
    kb.append(nav(back=f"an|open|{pid}", refresh=f"an|out|{pid}"))
    await show(target, "\n".join(lines), KB(inline_keyboard=kb))


async def send_video(message: Message, hub, asset_id: int) -> None:
    r = hub.db.one("SELECT * FROM assets WHERE id = ? AND asset_type = 'export:video'", (int(asset_id),))
    if not r:
        await message.answer("Ye video ab nahi mili.", parse_mode=None)
        return
    path = hub.settings.data_dir / r["relative_path"]
    meta = loads(r["metadata_json"], {})
    if not path.exists():
        await message.answer("⚠️ Video file laptop par nahi mili (shayad delete hui).", parse_mode=None)
        return
    caption = f"🎬 {meta.get('quality')} · {meta.get('width')}x{meta.get('height')} · {meta.get('seconds', 0):.0f}s (awaaz M8 me)"
    if path.stat().st_size > TG_LIMIT:
        await message.answer(f"{caption}\nFile {path.stat().st_size // (1024 * 1024)} MB hai — Telegram bot 50 MB se badi file nahi bhej sakta.\n"
                             f"Laptop par yahan hai:\n{path}", parse_mode=None)
        return
    await message.answer_video(FSInputFile(path), caption=caption, width=meta.get("width"), height=meta.get("height"),
                               duration=int(meta.get("seconds") or 0), supports_streaming=True, parse_mode=None)


@router.callback_query(F.data.func(lambda d: (c := parse(d)) is not None and c.area == "an"))
async def cb_anim(cb: CallbackQuery, hub) -> None:
    c = parse(cb.data)
    assert c is not None
    try:
        a = c.action
        if a == "pick":
            await answer(cb)
            await pick(cb, hub, c.int(0))
        elif a == "open":
            await answer(cb)
            await open_project(cb, hub, c.int(0))
        elif a == "still":
            pid = c.int(0)
            await answer(cb, "Photo bana raha hoon…")
            plan = planner.build(hub, pid, "preview")
            anim_jobs.require_pictures(plan)
            sc = plan["scenes"][0]

            def draw() -> bytes:
                from app.animation.two_d import puppet

                scene = planner.load_scene(hub, sc, 12)
                t = next((k["start"] + 0.3 for k in sc["talks"]), min(sc["duration"] / 2, 2.0))
                im = puppet.preview(scene, 960, 540, t)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=85)
                return buf.getvalue()

            data = await asyncio.to_thread(draw)
            m = _m(cb)
            if m:
                await m.answer_photo(BufferedInputFile(data, "scene1.jpg"), caption=f"Scene 1 ka ek frame ({sc['duration']:.0f}s scene)",
                                     parse_mode=None)
        elif a == "go":
            pid, quality = c.int(0), c.arg(1)
            if quality not in ("preview", "final"):
                raise ValueError("bad quality")
            m = _m(cb)
            key = f"anim:{pid}:{quality}:{m.chat.id}:{m.message_id}" if m else None
            job = anim_jobs.start(hub, pid, quality, chat_id=m.chat.id if m else None, key=key)
            hub.audit.record("anim_render", "queued", "project", pid, quality=quality, job=job["id"])
            await answer(cb, "Video job line me laga")
            if m:
                from app.telegram.handlers.jobs import send_card

                await send_card(m, hub, job["id"])
        elif a == "out":
            await answer(cb)
            await outputs(cb, hub, c.int(0))
        elif a == "send":
            await answer(cb, "Bhej raha hoon…")
            m = _m(cb)
            if m:
                await send_video(m, hub, c.int(0))
        else:
            await answer(cb, "Ye button purana ho gaya.", alert=True)
    except ValueError:
        await answer(cb, "Ye button purana ho gaya.", alert=True)
    except Exception as e:  # noqa: BLE001
        await fail(cb, e)


class VideoSender:
    """When a 2D render job finishes, send the video into the job's chat (once)."""

    def __init__(self, hub) -> None:
        self.hub = hub

    async def __call__(self, topic: str, data: dict) -> None:
        if data.get("status") != S.COMPLETED or self.hub.bot is None:
            return
        job = self.hub.jobs.get_job(data["job_id"])
        if job["job_type"] != anim_jobs.JOB or not job["chat_id"]:
            return
        out = loads(job["output_manifest"], {}) or {}
        if not out.get("asset_id"):
            return

        class _Target:  # minimal Message-like wrapper around bot.send_*
            def __init__(self, bot, chat_id):
                self.bot, self.chat_id = bot, chat_id

            async def answer(self, text, **kw):
                return await self.bot.send_message(self.chat_id, text, **kw)

            async def answer_video(self, video, **kw):
                return await self.bot.send_video(self.chat_id, video, **kw)

        try:
            await send_video(_Target(self.hub.bot, job["chat_id"]), self.hub, out["asset_id"])  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            from app.observability.log import get_logger

            get_logger(__name__).exception("video_send_failed")
