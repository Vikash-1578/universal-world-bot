"""Live progress message: ONE Telegram message that is edited as the agents work, so the owner never has to type 'status'.
Step changes are always sent; small detail updates are throttled (Telegram limits edits)."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.container import Hub

STEPS = [("research", "🔎 Research"), ("accuracy", "🧪 Accuracy"), ("script", "✍️ Script"), ("quality", "✅ Quality Checker")]
ICON = {"pending": "⬜", "running": "🔄", "done": "✅", "failed": "❌"}


class Live:
    def __init__(self, hub: "Hub", chat_id: int | None, job_id: int, topic: str) -> None:
        self.hub, self.chat_id, self.job_id, self.topic = hub, chat_id, job_id, topic
        self.state = {k: "pending" for k, _ in STEPS}
        self.detail: dict[str, str] = {}
        self.pct = 0.0
        self.current = "research"
        self.mid: int | None = None
        self._text = ""
        self._last = 0.0

    def render(self) -> str:
        lines = [f"🎬 Video #{self.job_id}: {self.topic[:45]} — {int(self.pct * 100)}%"]
        for k, label in STEPS:
            d = self.detail.get(k, "")
            lines.append(f"{ICON[self.state[k]]} {label}" + (f" — {d}" if d and self.state[k] != "pending" else ""))
        return "\n".join(lines)

    async def update(self, key: str, state: str | None = None, detail: str | None = None, pct: float | None = None) -> None:
        """State change (running/done/failed) is sent at once; detail-only changes are throttled."""
        self.current = key
        if detail is not None:
            self.detail[key] = detail[:90]
        if pct is not None:
            self.pct = max(self.pct, min(1.0, pct))
        changed = state is not None and state != self.state[key]
        if state is not None:
            self.state[key] = state
        await self._push(force=changed or state in ("done", "failed"))

    async def note(self, text: str) -> None:
        await self.update(self.current, detail=text)

    async def _push(self, force: bool) -> None:
        bot = self.hub.bot
        if bot is None or not self.chat_id:
            return
        text = self.render()
        now = time.monotonic()
        if text == self._text or (not force and now - self._last < 2.5):
            return
        try:
            if self.mid is None:
                self.mid = (await bot.send_message(self.chat_id, text, parse_mode=None)).message_id
            else:
                await bot.edit_message_text(text, chat_id=self.chat_id, message_id=self.mid, parse_mode=None)
            self._text, self._last = text, now
        except Exception:  # noqa: BLE001 - a failed edit must never stop the work
            pass
