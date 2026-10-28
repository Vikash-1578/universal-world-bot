"""Conversation replies (text the bot asked for) and safe handling of anything else."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from app.telegram.keyboards.menus import main_menu
from app.telegram.ui import answer, fail

router = Router(name="fallback")
MAX_TEXT = 20_000


@router.message()
async def on_message(message: Message, hub) -> None:
    uid = message.from_user.id if message.from_user else 0
    st = hub.extra["conv"].get(uid)
    if st and not message.text and (message.document or message.voice or message.audio or message.photo):
        from app.telegram.handlers import studio

        try:
            if await studio.on_media(message, hub, st["step"], st["data"]):
                return
        except Exception as e:  # noqa: BLE001
            await fail(message, e)
            return
    if st and message.text:
        if len(message.text) > MAX_TEXT:
            await message.answer("⚠️ Text bahut lamba hai (20,000 akshar tak). File (.txt) bana ke bhejo.", parse_mode=None)
            return
        from app.telegram.handlers import projects, studio

        handlers = [projects.on_text, studio.on_text, *hub.extra.get("text_handlers", [])]
        try:
            for h in handlers:
                if await h(message, hub, st["step"], st["data"]):
                    return
        except Exception as e:  # noqa: BLE001
            await fail(message, e)
            return
    await message.answer("Menu se kaam chuno 👇", reply_markup=main_menu(), parse_mode=None)


@router.callback_query()
async def on_unknown_callback(cb: CallbackQuery) -> None:
    await answer(cb, "Ye button purana ho gaya. /menu se dobara kholo.", alert=True)
