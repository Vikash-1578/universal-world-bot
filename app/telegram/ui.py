"""Small helpers shared by handlers: show a screen (edit if possible, else send), friendly errors."""
from __future__ import annotations

import time
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.core.errors import HubError
from app.observability.log import get_logger

log = get_logger(__name__)


async def show(target: Message | CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> Message | None:
    text = text[:4000]
    if isinstance(target, CallbackQuery):
        msg = target.message
        if isinstance(msg, Message):
            try:
                return await msg.edit_text(text, reply_markup=kb, parse_mode=None)  # type: ignore[return-value]
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return msg
            return await msg.answer(text, reply_markup=kb, parse_mode=None)
        return None
    return await target.answer(text, reply_markup=kb, parse_mode=None)


async def answer(cb: CallbackQuery, text: str = "", alert: bool = False) -> None:
    try:
        await cb.answer(text[:190], show_alert=alert)
    except TelegramBadRequest:
        pass  # query too old: nothing to do


async def fail(target: Message | CallbackQuery, e: Exception) -> None:
    text = e.user_message if isinstance(e, HubError) else "Kuch gadbad hui. Logs me detail hai, dobara try karo."
    if not isinstance(e, HubError):
        log.exception("handler_error")
    if isinstance(target, CallbackQuery):
        await answer(target, text, alert=True)
    else:
        await target.answer("⚠️ " + text, parse_mode=None)


def ago(ts: float | None) -> str:
    if not ts:
        return "-"
    d = max(0, time.time() - ts)
    if d < 90:
        return "abhi"
    if d < 3600:
        return f"{int(d // 60)} min pehle"
    if d < 86400:
        return f"{int(d // 3600)} ghante pehle"
    return f"{int(d // 86400)} din pehle"


def bar(fraction: float, width: int = 10) -> str:
    n = max(0, min(width, round(fraction * width)))
    return "▓" * n + "░" * (width - n)


def hub_of(data: dict[str, Any]):
    return data["hub"]
