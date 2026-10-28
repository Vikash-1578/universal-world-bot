"""Guided-conversation state, persisted in SQLite so a restart does not lose "what the bot was waiting for"."""
from __future__ import annotations

import time
from typing import Any

from app.storage.db import Database

TTL = 6 * 3600


class Conversations:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, user_id: int) -> dict | None:
        st = self.db.get_setting(f"conv:{user_id}")
        if not st or st.get("expires", 0) < time.time():
            return None
        return st

    def set(self, user_id: int, step: str, **data: Any) -> dict:
        st = {"step": step, "data": data, "expires": time.time() + TTL}
        self.db.set_setting(f"conv:{user_id}", st)
        return st

    def update(self, user_id: int, **data: Any) -> dict | None:
        st = self.get(user_id)
        if st is None:
            return None
        st["data"].update(data)
        st["expires"] = time.time() + TTL
        self.db.set_setting(f"conv:{user_id}", st)
        return st

    def clear(self, user_id: int) -> None:
        self.db.execute("DELETE FROM settings WHERE key = ?", (f"conv:{user_id}",))
