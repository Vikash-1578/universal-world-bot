"""Single-owner security.

* `OwnerGate` — aiogram middleware: every message / callback from anyone except the owner is dropped
  (with a short reply so the owner can find their own id during setup).
* `Approvals` — one-time, expiring approval tokens. Sensitive services (model install, cloud use, deletion,
  final export) *require* a valid token; a Telegram button alone is never the security boundary.
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.core.errors import ApprovalRequired, Forbidden
from app.observability.audit import Audit
from app.observability.log import get_logger
from app.storage.db import Database, dumps, loads

log = get_logger(__name__)

SENSITIVE = {"model_install", "model_update", "cloud_enable", "delete_project", "delete_asset", "final_export",
             "restore_backup", "cleanup"}


def user_of(event: TelegramObject) -> int:
    u = getattr(event, "from_user", None)
    return int(u.id) if u else 0


class OwnerGate(BaseMiddleware):
    def __init__(self, owner_id: int, audit: Audit | None = None) -> None:
        self.owner_id = int(owner_id or 0)
        self.audit = audit
        self._warned: dict[int, float] = {}

    def allowed(self, uid: int) -> bool:
        return self.owner_id > 0 and uid == self.owner_id

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        uid = user_of(event)
        if self.allowed(uid):
            return await handler(event, data)
        if self.audit is not None:
            self.audit.record("unauthorized", "denied", "user", uid)
        log.warning("denied user=%s", uid)
        now = time.time()
        if now - self._warned.get(uid, 0) > 600:  # answer at most once per 10 min per user
            self._warned[uid] = now
            text = ("⛔ Ye private bot hai." if self.owner_id
                    else f"⚙️ Setup baaki hai. Tumhari Telegram ID: {uid}\n.env me OWNER_ID={uid} likho aur bot restart karo.")
            try:
                if isinstance(event, Message):
                    await event.answer(text, parse_mode=None)
                elif isinstance(event, CallbackQuery):
                    await event.answer("⛔ Private bot", show_alert=True)
            except Exception:  # noqa: BLE001
                pass
        return None

    def check(self, uid: int) -> None:
        """For service-level checks (defence in depth)."""
        if not self.allowed(uid):
            raise Forbidden("Ye kaam sirf owner kar sakta hai.")


class Approvals:
    TTL = 15 * 60

    def __init__(self, db: Database, audit: Audit | None = None) -> None:
        self.db = db
        self.audit = audit

    def request(self, action: str, target: Any, payload: dict | None = None, ttl: float | None = None) -> str:
        token = secrets.token_urlsafe(9)
        now = time.time()
        self.db.insert("approvals", {"token": token, "action": action, "target": str(target),
                                     "payload_json": dumps(payload or {}), "created_at": now,
                                     "expires_at": now + (ttl or self.TTL)})
        return token

    def consume(self, token: str, action: str, target: Any) -> dict:
        """Validate + burn a token. Raises ApprovalRequired if missing, expired, used or for another action."""
        row = self.db.one("SELECT * FROM approvals WHERE token = ?", (token or "",))
        now = time.time()
        ok = (row is not None and row["action"] == action and row["target"] == str(target)
              and row["used_at"] is None and row["expires_at"] >= now)
        if not ok:
            if self.audit is not None:
                self.audit.record(action, "approval_rejected", "target", target)
            raise ApprovalRequired("Ye approval purana ya galat hai. Dobara try karo.")
        n = self.db.execute("UPDATE approvals SET used_at = ? WHERE token = ? AND used_at IS NULL", (now, token)).rowcount
        if n != 1:
            raise ApprovalRequired("Ye approval pehle hi use ho chuka hai.")
        if self.audit is not None:
            self.audit.record(action, "approved", "target", target)
        return loads(row["payload_json"], {})

    def invalidate(self, action: str, target: Any) -> int:
        return self.db.execute("UPDATE approvals SET used_at = ? WHERE action = ? AND target = ? AND used_at IS NULL",
                               (time.time(), action, str(target))).rowcount
