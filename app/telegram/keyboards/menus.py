"""Inline keyboards. Short labels so they fit on a phone screen."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton as B
from aiogram.types import InlineKeyboardMarkup as KB

from app.telegram.callbacks.codec import make

# (key, label, milestone that makes it work; 0 = available now)
MAIN = [
    ("projects", "📁 Projects", 0), ("new", "🎬 New Production", 0),
    ("script", "📜 Script Studio", 0), ("storyboard", "🎞 Storyboard", 0),
    ("characters", "🧍 Characters", 0), ("environments", "🏞 Environments", 0),
    ("animation", "🎭 Animation", 6), ("audio", "🎤 Audio", 8),
    ("subtitles", "💬 Subtitles", 8), ("models", "🧠 Model Manager", 9),
    ("jobs", "⏳ Job Queue", 0), ("export", "📤 Render & Export", 6),
    ("assets", "🗂 Assets & Storage", 10), ("backups", "💾 Backups", 10),
    ("settings", "⚙️ Settings", 0), ("diag", "🩺 Diagnostics", 0),
    ("help", "❓ Help", 0),
]
AVAILABLE: dict[str, int] = {k: m for k, _, m in MAIN}


def main_menu() -> KB:
    rows, row = [], []
    for key, label, _ in MAIN:
        row.append(B(text=label, callback_data=make("m", key)))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return KB(inline_keyboard=rows)


def nav(back: str | None = "m|home", refresh: str | None = None, cancel: bool = False) -> list[B]:
    row = []
    if back:
        area, action, *args = back.split("|")
        row.append(B(text="◀ Back", callback_data=make(area, action, *args)))
    if refresh:
        area, action, *args = refresh.split("|")
        row.append(B(text="🔄 Refresh", callback_data=make(area, action, *args)))
    if cancel:
        row.append(B(text="✖ Cancel", callback_data=make("m", "cancel")))
    return row


def pager(area: str, action: str, page: int, total: int, per: int, *extra: object) -> list[B]:
    pages = max(1, (total + per - 1) // per)
    row = []
    if page > 0:
        row.append(B(text="◀", callback_data=make(area, action, page - 1, *extra)))
    row.append(B(text=f"{page + 1}/{pages}", callback_data=make("m", "noop")))
    if page + 1 < pages:
        row.append(B(text="▶", callback_data=make(area, action, page + 1, *extra)))
    return row


def confirm(area: str, action: str, *args: object, yes: str = "✅ Haan", no_back: str = "m|home") -> KB:
    area_b, action_b, *args_b = no_back.split("|")
    return KB(inline_keyboard=[[B(text=yes, callback_data=make(area, action, *args)),
                                B(text="✖ Nahi", callback_data=make(area_b, action_b, *args_b))]])
