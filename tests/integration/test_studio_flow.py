"""Script -> approve -> storyboard draft job -> edit -> approve, through Telegram buttons (fake Telegram session)."""
from app.telegram.callbacks.codec import make
from tests.helpers import TempDirCase, buttons, cb_update, feed, make_bot_and_dp, make_hub, msg_update, texts
from tests.unit.test_script_storyboard import SCRIPT, FakeLLM


class StudioFlowTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.hub.llm = FakeLLM(ok=False)
        self.hub.storyboards.llm = self.hub.llm
        self.bot, self.dp, self.sess = make_bot_and_dp(self.hub)
        self.pid = self.hub.projects.create_project("Race", "2d")["id"]

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
        await feed(self.bot, self.dp, cb_update(make("sb", "draft", pid)))
        self.assertIn("approve", self.sess.calls[-1][1].text.lower())  # alert: approve script first
        await feed(self.bot, self.dp, cb_update(make("ss", "approve", v["id"])))
        self.assertIsNone(self.hub.scripts.approved(pid))  # confirmation needed
        await feed(self.bot, self.dp, cb_update(make("ss", "approve_ok", v["id"])))
        self.assertEqual(self.hub.scripts.approved(pid)["id"], v["id"])
        await feed(self.bot, self.dp, cb_update(make("sb", "draft", pid), message_id=61))
        await self.hub.jobs.wait_idle()
        scenes = self.hub.storyboards.scenes(pid)
        self.assertEqual(len(scenes), 3)
        await feed(self.bot, self.dp, cb_update(make("sb", "sc", pid, 0)))
        self.assertIn("Scene 1/3", texts(self.sess)[-1])
        await feed(self.bot, self.dp, cb_update(make("sb", "shot", pid, scenes[0]["id"], 0)))
        self.assertEqual(self.hub.storyboards.scene(pid, scenes[0]["id"])["camera"]["shot"], "medium")
        await feed(self.bot, self.dp, cb_update(make("sb", "edit", pid, scenes[1]["id"], "environment_ref")))
        await feed(self.bot, self.dp, msg_update("Toota hua lakdi ka pul"))
        self.assertEqual(self.hub.storyboards.scene(pid, scenes[1]["id"])["environment_ref"], "Toota hua lakdi ka pul")
        await feed(self.bot, self.dp, cb_update(make("sb", "mv", pid, scenes[2]["id"], 2, "u")))
        self.assertEqual(self.hub.storyboards.scene(pid, scenes[2]["id"])["scene_number"], 2)
        await feed(self.bot, self.dp, cb_update(make("sb", "regen", pid, scenes[0]["id"])))
        self.assertIn("AI band", self.sess.calls[-1][1].text)
        await feed(self.bot, self.dp, cb_update(make("sb", "approve_ok", pid)))
        self.assertTrue(self.hub.storyboards.is_approved(pid))
        await feed(self.bot, self.dp, cb_update(make("sb", "draft", pid, "replace")))
        token_btn = [b for b in buttons(self.sess) if b.startswith("v1|sb|draft_ok|")][0]
        await feed(self.bot, self.dp, cb_update(make("sb", "draft_ok", pid, "forged")))
        self.assertTrue(self.hub.storyboards.is_approved(pid))  # forged token: nothing replaced
        self.assertTrue(token_btn)
