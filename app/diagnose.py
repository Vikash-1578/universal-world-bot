"""`python -m app.diagnose` — prints the diagnostics report. Exit code 1 if anything critical fails."""
from __future__ import annotations

import sys

from app.core.config import load_settings
from app.observability.diagnostics import FAIL, run_all, summary

CRITICAL = {"Python", "FFmpeg", "Database", "Config"}


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")  # Windows consoles without UTF-8
    except (AttributeError, ValueError):
        pass
    s = load_settings()
    checks = run_all(s)
    print(summary(checks))
    return 1 if any(c.status == FAIL and c.name in CRITICAL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
