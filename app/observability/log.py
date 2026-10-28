"""Logging that never prints secrets: every message is passed through a redactor."""
from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

_SECRETS: set[str] = set()
_PATTERNS = [
    re.compile(r"\b\d{5,12}:[A-Za-z0-9_-]{30,}\b"),          # telegram bot token
    re.compile(r"\b(?:sk|gsk|csk|AIza|hf|nvapi)[-_A-Za-z0-9]{12,}\b"),  # common API key shapes
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)([?&](?:key|token|api_key)=)[^&\s]+"),
]


def add_secret(value: str) -> None:
    if value and len(value) >= 8:
        _SECRETS.add(value)


def redact(text: str) -> str:
    s = str(text)
    for v in sorted(_SECRETS, key=len, reverse=True):
        s = s.replace(v, "***")
    for p in _PATTERNS:
        s = p.sub(lambda m: (m.group(1) if m.lastindex else "") + "***", s)
    return s


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        record.msg, record.args = redact(msg), None
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def setup(level: str = "INFO", log_dir: Path | None = None) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(log_dir / "hub.log", maxBytes=5_000_000, backupCount=5,
                                                             encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(RedactFilter())
        root.addHandler(h)
    for noisy in ("aiogram.event", "httpx", "asyncio"):
        logging.getLogger(noisy).setLevel("WARNING")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
