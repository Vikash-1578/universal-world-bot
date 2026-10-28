"""Simple per-user rate limit (protects the laptop from runaway button mashing / loops)."""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class RateLimit(BaseMiddleware):
    def __init__(self, per_minute: int = 60) -> None:
        self.per_minute = per_minute
        self.hits: dict[int, deque[float]] = {}

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        u = getattr(event, "from_user", None)
        uid = u.id if u else 0
        q = self.hits.setdefault(uid, deque())
        now = time.time()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("Thoda dheere 🙂", show_alert=False)
                except Exception:  # noqa: BLE001
                    pass
            elif isinstance(event, Message) and len(q) == self.per_minute:
                await event.answer("Bahut tez messages aa rahe hain, 1 minute ruk ke try karo.", parse_mode=None)
            q.append(now)
            return None
        q.append(now)
        return await handler(event, data)
