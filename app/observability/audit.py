"""Owner's own audit trail: what was done, on what, and whether it worked. Details are redacted."""
from __future__ import annotations

import time
from typing import Any

from app.observability.log import redact
from app.storage.db import Database, dumps


class Audit:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, action: str, result: str = "ok", target_type: str = "", target_id: Any = "", **details: Any) -> None:
        clean = {k: redact(str(v))[:500] for k, v in details.items()}
        self.db.insert("audit_events", {
            "action": action, "target_type": target_type, "target_id": str(target_id), "result": result,
            "created_at": time.time(), "details_redacted_json": dumps(clean),
        })

    def recent(self, limit: int = 20) -> list[dict]:
        return self.db.all("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))
