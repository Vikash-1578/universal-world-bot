"""Callback data: short, versioned, validated. Format `v1|area|action|arg1|arg2` (<= 64 bytes, Telegram limit).

Only ids and short tokens go in callback data — never stories, paths or secrets. Every handler re-checks
that the referenced object exists (an old button for a deleted project just shows "purana button").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

VERSION = "v1"
_PART = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")


@dataclass(frozen=True)
class CB:
    area: str
    action: str
    args: tuple[str, ...] = ()

    def int(self, i: int = 0) -> int:
        try:
            return int(self.args[i])
        except (IndexError, ValueError):
            raise ValueError("bad id") from None

    def arg(self, i: int = 0, default: str = "") -> str:
        return self.args[i] if i < len(self.args) else default


def make(area: str, action: str, *args: object) -> str:
    parts = [VERSION, area, action, *[str(a) for a in args]]
    for p in parts:
        if not _PART.match(p):
            raise ValueError(f"bad callback part: {p!r}")
    data = "|".join(parts)
    if len(data.encode()) > 64:
        raise ValueError("callback data too long")
    return data


def parse(data: str | None) -> CB | None:
    if not data or len(data.encode()) > 64:
        return None
    parts = data.split("|")
    if len(parts) < 3 or parts[0] != VERSION or not all(_PART.match(p) for p in parts):
        return None
    return CB(parts[1], parts[2], tuple(parts[3:]))
