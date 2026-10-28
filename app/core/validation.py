"""Configuration validation: plain-language problems + how to fix them. Never prints secret values."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import Settings

TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")


@dataclass
class Problem:
    level: str  # "error" stops start-up, "warn" is shown in diagnostics
    what: str
    fix: str


def validate(s: Settings) -> list[Problem]:
    out: list[Problem] = []
    if not s.bot_token:
        out.append(Problem("error", "Telegram bot token nahi mila",
                           ".env file me BOT_TOKEN=... likho (@BotFather -> /mybots -> API Token)."))
    elif not TOKEN_RE.match(s.bot_token):
        out.append(Problem("error", "Bot token ka format galat lag raha hai",
                           "@BotFather se token dobara copy karo, aage-peeche space na ho."))
    if s.owner_id <= 0:
        out.append(Problem("error", "OWNER_ID set nahi hai (bot kisi ke liye nahi chalega)",
                           "Bot start karke use message bhejo, wo tumhari ID batayega. Phir .env me OWNER_ID=<id> likho."))
    if s.max_heavy_workers < 1 or s.max_heavy_workers > 4:
        out.append(Problem("warn", "max_heavy_workers 1-4 ke beech hona chahiye", "config/config.toml me theek karo."))
    if s.fps not in (24, 25, 30, 60):
        out.append(Problem("warn", f"fps={s.fps} unusual hai", "24 ya 30 rakho."))
    try:
        test = s.data_dir / ".write_test"
        test.write_text("ok", encoding="utf-8")
        test.unlink()
    except OSError:
        out.append(Problem("error", f"Data folder me likh nahi pa rahe: {s.data_dir}",
                           "Folder ki permission dekho ya config.toml me data_dir badlo."))
    return out


def errors(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level == "error"]
