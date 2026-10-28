"""Tiny in-process event bus so services (scheduler, renderers) can report progress
without importing Telegram code. Telegram subscribes and edits job cards."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

from app.observability.log import get_logger

log = get_logger(__name__)
Handler = Callable[[str, dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    async def publish(self, topic: str, **data: Any) -> None:
        for h in list(self._subs.get(topic, [])) + list(self._subs.get("*", [])):
            try:
                await h(topic, data)
            except Exception as e:  # a broken listener must never break a job
                log.warning("event_handler_failed topic=%s err=%s", topic, type(e).__name__)

    def publish_nowait(self, topic: str, **data: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.publish(topic, **data))
