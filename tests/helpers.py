"""Test helpers. Everything here is a TEST DOUBLE (fake Telegram session, temp folders) — it proves our own
logic, not that Telegram, AI or rendering services work. Real-tool tests are marked with @needs_ffmpeg etc."""
from __future__ import annotations

import datetime
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from app.container import Hub, build_hub
from app.core.config import Settings

OWNER = 1001
STRANGER = 2002
TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def make_settings(tmp: Path, **kw: Any) -> Settings:
    s = Settings(bot_token=TOKEN, owner_id=OWNER, base_dir=tmp, data_dir=tmp / "data", keys=[("groq", "gsk_testkey1234567890")])
    s.data_dir.mkdir(parents=True, exist_ok=True)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def make_hub(tmp: Path, **kw: Any) -> Hub:
    return build_hub(make_settings(tmp, **kw))


def has_ffmpeg() -> bool:
    try:
        import imageio_ffmpeg  # noqa: F401

        return True
    except ImportError:
        return shutil.which("ffmpeg") is not None


needs_ffmpeg = unittest.skipUnless(has_ffmpeg(), "FFmpeg not installed")


class TempDirCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()


# ------------------------------------------------------------------ fake Telegram (test double)
CHAT = {"id": OWNER, "type": "private"}


def user(uid: int) -> dict:
    return {"id": uid, "is_bot": False, "first_name": "U"}


_n = [0]


def msg_update(text: str, uid: int = OWNER, **extra: Any) -> dict:
    _n[0] += 1
    m = {"message_id": 100 + _n[0], "date": 1700000000, "chat": {"id": uid, "type": "private"}, "from": user(uid), "text": text}
    if text.startswith("/"):
        m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    m.update(extra)
    return {"update_id": _n[0], "message": m}


def cb_update(data: str, message_id: int = 50, uid: int = OWNER) -> dict:
    _n[0] += 1
    msg = {"message_id": message_id, "date": 1700000000, "chat": {"id": uid, "type": "private"},
           "from": {"id": 999, "is_bot": True, "first_name": "Bot"}, "text": "x"}
    return {"update_id": _n[0], "callback_query": {"id": f"q{_n[0]}", "from": user(uid), "chat_instance": "ci",
                                                   "data": data, "message": msg}}


def make_bot_and_dp(hub: Hub):
    from aiogram import Bot, Dispatcher
    from aiogram.client.session.base import BaseSession
    from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText
    from aiogram.types import Chat, Message, User

    class Sess(BaseSession):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, Any]] = []
            self.n = 500

        async def close(self) -> None:
            pass

        async def stream_content(self, *a, **k):  # pragma: no cover
            raise NotImplementedError

        async def make_request(self, bot, method, timeout=None):
            name = type(method).__name__
            self.calls.append((name, method))
            if isinstance(method, AnswerCallbackQuery) or isinstance(method, EditMessageReplyMarkup):
                return True
            if name == "GetMe":
                return User(id=999, is_bot=True, first_name="Bot", username="test_bot")
            self.n += 1
            chat_id = getattr(method, "chat_id", OWNER) or OWNER
            text = getattr(method, "text", None)
            mid = getattr(method, "message_id", None) if isinstance(method, EditMessageText) else self.n
            return Message(message_id=mid or self.n, date=datetime.datetime.now(), chat=Chat(id=int(chat_id), type="private"),
                           text=text).as_(bot)

    from app.telegram.setup import setup_dispatcher

    sess = Sess()
    bot = Bot(TOKEN, session=sess)
    dp = Dispatcher()
    setup_dispatcher(dp, hub)
    hub.bot = bot
    return bot, dp, sess


async def feed(bot, dp, update: dict) -> None:
    from aiogram.types import Update

    await dp.feed_update(bot, Update.model_validate(update, context={"bot": bot}))


def texts(sess, name: str | None = None) -> list[str]:
    out = []
    for n, m in sess.calls:
        if name and n != name:
            continue
        t = getattr(m, "text", None)
        if t:
            out.append(t)
    return out


def buttons(sess) -> list[str]:
    for n, m in reversed(sess.calls):
        kb = getattr(m, "reply_markup", None)
        if kb is not None and hasattr(kb, "inline_keyboard"):
            return [b.callback_data for row in kb.inline_keyboard for b in row]
    return []
