"""Entry point: `python -m app.main` (or scripts/start.ps1).

Start-up order: settings -> validation -> logging (with secret redaction) -> database migrations ->
services -> Telegram polling. If the configuration is incomplete the process explains what is
missing and exits instead of starting an unprotected bot.
"""
from __future__ import annotations

import asyncio
import signal
import sys

from app.container import Hub, build_hub
from app.core.config import load_settings
from app.core.validation import errors, validate
from app.observability import log as logmod

log = logmod.get_logger("app.main")


async def run(hub: Hub) -> None:
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties

    from app.telegram.setup import setup_dispatcher

    bot = Bot(hub.settings.bot_token, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher()
    setup_dispatcher(dp, hub)
    me = await bot.get_me()
    hub.status["telegram"] = f"connected as @{me.username}"
    log.info("telegram connected as @%s, owner=%s", me.username, "set" if hub.settings.owner_id else "MISSING")
    await hub.start(bot)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # Windows: Ctrl+C raises KeyboardInterrupt instead
            pass
    polling = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    try:
        await asyncio.wait([polling, asyncio.create_task(stop.wait())], return_when=asyncio.FIRST_COMPLETED)
    finally:
        log.info("shutting down: finishing current job stage, saving state...")
        if not polling.done():
            await dp.stop_polling()
        await hub.stop()
        await bot.session.close()
        log.info("stopped cleanly")


def main() -> int:
    settings = load_settings()
    logmod.setup(settings.log_level, settings.base_dir / "logs")
    for secret in [settings.bot_token, *[v for _, v in settings.keys]]:
        logmod.add_secret(secret)
    problems = validate(settings)
    for p in problems:
        (log.error if p.level == "error" else log.warning)("%s -> %s", p.what, p.fix)
    bad = errors(problems)
    # Missing OWNER_ID alone is allowed: the bot then only tells the sender their own id (setup mode).
    if any("token" in p.what.lower() or "data folder" in p.what.lower() for p in bad):
        print("\nBot start nahi ho sakta. Upar likhi problem theek karo, phir dobara chalao.")
        return 2
    hub = build_hub(settings)
    try:
        asyncio.run(run(hub))
    except KeyboardInterrupt:
        print("\nBot band ho gaya (Ctrl+C).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
