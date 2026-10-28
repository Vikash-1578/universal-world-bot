"""Registers job handlers. Each milestone adds its own; unregistered job types simply stay queued."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.container import Hub


def register_all(hub: "Hub") -> None:
    from app.observability.selftest import register as reg_selftest

    reg_selftest(hub)
