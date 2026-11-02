"""Script -> send -> approve, through Telegram buttons (fake Telegram session)."""
from app.telegram.callbacks.codec import make
from tests.helpers import TempDirCase, buttons, cb_update, feed, make_bot_and_dp, make_hub, msg_update, texts
from tests.unit.test_scripts import SCRIPT, FakeLLM


class StudioFlowTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.hub.llm = FakeLLM(ok=False)
        self.bot, self.dp, self.sess = make_bot_and_dp(self.hub)
        self.pid = self.hub.projects.create_project("Race", "slideshow")["id"]

    async def asyncTearDown(self):
        await self.hub.jobs.stop(grace=1)
        self.hub.db.close()
        await super().asyncTearDown()

    async def test_full_flow(self):
        pid = self.pid
        await feed(self.bot, self.dp, cb_update(make("m", "script")))
        self.assertIn(make("ss", "open", pid), buttons(self.sess))
        await feed(self.bot, self.dp, cb_update(make("ss", "open", pid)))
        self.assertIn("AI: band", texts(self.sess)[-1])
        await feed(self.bot, self.dp, cb_update(make("ss", "ai", pid)))
        self.assertIn("Ollama", texts(self.sess)[-1])  # honest: no AI available
        await feed(self.bot, self.dp, cb_update(make("ss", "send", pid)))
        await feed(self.bot, self.dp, msg_update(SCRIPT))
        v = self.hub.scripts.latest(pid)
        self.assertEqual(v["approval_status"], "draft")
        self.assertTrue(any("Characters: Khargosh, Sher, Kachhua" in t for t in texts(self.sess)))
        await feed(self.bot, self.dp, cb_update(make("ss", "approve", v["id"])))
        self.assertIsNone(self.hub.scripts.approved(pid))  # confirmation needed
        await feed(self.bot, self.dp, cb_update(make("ss", "approve_ok", v["id"])))
        self.assertEqual(self.hub.scripts.approved(pid)["id"], v["id"])
