"""Main menu, help, settings (cloud opt-in), diagnostics, and honest "coming in milestone N" screens."""
from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as KB, Message

from app.telegram.callbacks.codec import make, parse
from app.telegram.keyboards.menus import AVAILABLE, MAIN, confirm, main_menu, nav
from app.telegram.ui import answer, fail, show

router = Router(name="home")

HOME_TEXT = ("🌍 Universal World — Video Production Hub\n\n"
             "Neeche se kaam chuno. Jo hissa abhi ban raha hai wo saaf batayega ki kis milestone me aayega.")

HELP_TEXT = ("❓ Help\n\n"
             "• 📁 Projects — tumhare saare video projects. Kholo, naam/settings badlo, version save karo.\n"
             "• 🎬 New Production — naya project (2D cartoon / 3D Blender / images + narration).\n"
             "• 📜 Script Studio — script bhejo (text/file/voice) ya AI se likhwao, versions, approve.\n"
             "• 🎞 Storyboard — approved script se scenes; shot/jagah/time badlo, upar-neeche karo, phir approve.\n"
             "• 🧍 Characters / 🏞 Environments — apni library: image do (background apne aap hatta hai), expressions, poses, "
             "1100+ templates, package export/import. Project me 🎭 Casting se script ke characters ko library item do.\n"
             "• ⏳ Job Queue — lambe kaam (render, awaaz...) yahan chalte hain. Pause, resume, cancel, retry.\n"
             "• ⚙️ Settings — Cloud AI on/off. Default OFF: koi paid/cloud service bina tumhari permission ke nahi chalegi.\n"
             "• 🩺 Diagnostics — laptop, GPU, FFmpeg, Blender, database ki jaanch + self-test video.\n\n"
             "Bot laptop par chalta hai. Laptop band / so gaya ya terminal band hua = bot jawab nahi dega. "
             "Dobara chalane ke liye scripts\\start.ps1 chalao.\n\n"
             "Kahin bhi atak jao: /menu likho.")


def coming_soon(key: str) -> str:
    label = next(lbl for k, lbl, _ in MAIN if k == key)
    m = AVAILABLE[key]
    return (f"{label}\n\n🚧 Ye hissa Milestone {m} me banega. Abhi kaam nahi karta — "
            f"jab tak wo test na ho jaye, bot ise chalne wala nahi batayega.\n\n"
            "Abhi chalne wale: Projects, New Production, Script Studio, Storyboard, Characters, Environments, Job Queue, Settings, Diagnostics, Help.")


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, hub) -> None:
    if message.from_user:
        hub.extra["conv"].clear(message.from_user.id)
    await message.answer(HOME_TEXT, reply_markup=main_menu(), parse_mode=None)


@router.callback_query(F.data.func(lambda d: (c := parse(d)) is not None and c.area == "m"))
async def cb_menu(cb: CallbackQuery, hub) -> None:
    c = parse(cb.data)
    assert c is not None
    try:
        if c.action == "noop":
            await answer(cb)
            return
        if c.action in ("home", "cancel"):
            hub.extra["conv"].clear(cb.from_user.id)
            await answer(cb, "Cancel" if c.action == "cancel" else "")
            await show(cb, HOME_TEXT, main_menu())
            return
        if c.action == "help":
            await answer(cb)
            await show(cb, HELP_TEXT, KB(inline_keyboard=[nav()]))
            return
        if c.action == "settings":
            await answer(cb)
            await show_settings(cb, hub)
            return
        if c.action == "diag":
            await answer(cb, "Jaanch chal rahi hai...")
            await show_diagnostics(cb, hub)
            return
        if c.action in ("characters", "environments"):
            from app.telegram.handlers.library import home as lib_home

            await answer(cb)
            await lib_home(cb, hub, "c" if c.action == "characters" else "e")
            return
        if c.action in ("script", "storyboard"):
            from app.telegram.handlers.studio import pick_project

            await answer(cb)
            await pick_project(cb, hub, "ss" if c.action == "script" else "sb", 0)
            return
        if c.action in ("projects", "new", "jobs"):
            from app.telegram.handlers import jobs, projects

            await answer(cb)
            if c.action == "projects":
                await projects.show_list(cb, hub, 0)
            elif c.action == "new":
                await projects.start_new(cb, hub)
            else:
                await jobs.show_list(cb, hub, 0)
            return
        if c.action in AVAILABLE:
            await answer(cb)
            await show(cb, coming_soon(c.action), KB(inline_keyboard=[nav()]))
            return
        await answer(cb, "Ye button purana ho gaya.", alert=True)
    except Exception as e:  # noqa: BLE001
        await fail(cb, e)


async def show_settings(target, hub) -> None:
    on = hub.cloud_enabled
    providers = sorted({k for k, _ in hub.settings.keys})
    text = ("⚙️ Settings\n\n"
            f"☁️ Cloud AI: {'ON ✅' if on else 'OFF ⛔'}\n"
            "OFF = koi bhi cloud/paid AI service use nahi hogi, sirf laptop par chalne wale tools.\n"
            "ON = keys.txt me di gayi services (jaise Groq, Gemini, Cloudflare) story/awaaz/images ke liye use ho sakti hain. "
            "Inme free limit hoti hai; limit ke baad kuch services paise maang sakti hain.\n\n"
            f"keys.txt me providers: {', '.join(providers) if providers else 'koi nahi'}")
    kb = KB(inline_keyboard=[
        [B(text="☁️ Cloud AI band karo" if on else "☁️ Cloud AI chalu karo", callback_data=make("s", "cloud", "off" if on else "ask"))],
        nav(),
    ])
    await show(target, text, kb)


@router.callback_query(F.data.func(lambda d: (c := parse(d)) is not None and c.area == "s"))
async def cb_settings(cb: CallbackQuery, hub) -> None:
    c = parse(cb.data)
    assert c is not None
    try:
        if c.action == "cloud" and c.arg() == "ask":
            token = hub.approvals.request("cloud_enable", "global")
            await answer(cb)
            await show(cb, "☁️ Cloud AI chalu karna hai?\n\nTumhari story/text in services ko bheja jayega. "
                           "Private photos/videos kabhi bina poochhe upload nahi honge. Pakka?",
                       confirm("s", "cloud_ok", token, no_back="m|settings"))
        elif c.action == "cloud_ok":
            hub.approvals.consume(c.arg(), "cloud_enable", "global")
            hub.set_cloud(True)
            await answer(cb, "Cloud AI ON")
            await show_settings(cb, hub)
        elif c.action == "cloud" and c.arg() == "off":
            hub.set_cloud(False)
            await answer(cb, "Cloud AI OFF")
            await show_settings(cb, hub)
        else:
            await answer(cb, "Ye button purana ho gaya.", alert=True)
    except Exception as e:  # noqa: BLE001
        await fail(cb, e)


async def show_diagnostics(target, hub) -> None:
    from app.observability.diagnostics import run_all, summary

    checks = await asyncio.to_thread(run_all, hub.settings, True)
    lines = [f"🩺 Diagnostics\n", summary(checks), "",
             f"Telegram: {hub.status.get('telegram', '?')}", f"Scheduler: {hub.status.get('scheduler', '?')}"]
    kb = KB(inline_keyboard=[[B(text="🧪 Self-test video chalao", callback_data=make("d", "selftest"))],
                             nav(refresh="m|diag")])
    await show(target, "\n".join(lines), kb)


@router.callback_query(F.data.func(lambda d: (c := parse(d)) is not None and c.area == "d"))
async def cb_diag(cb: CallbackQuery, hub) -> None:
    c = parse(cb.data)
    try:
        if c and c.action == "selftest" and isinstance(cb.message, Message):
            key = f"selftest:{cb.message.chat.id}:{cb.message.message_id}"
            job = hub.jobs.submit_job("selftest", None, {}, 3, idempotency_key=key, chat_id=cb.message.chat.id)
            await answer(cb, "Self-test job line me laga diya")
            from app.telegram.handlers.jobs import send_card

            await send_card(cb.message, hub, job["id"])
        else:
            await answer(cb, "Ye button purana ho gaya.", alert=True)
    except Exception as e:  # noqa: BLE001
        await fail(cb, e)
