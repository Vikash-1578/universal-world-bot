"""Owner-only access, forged / stale callbacks, destructive-action confirmation. Uses a fake Telegram session."""
from app.telegram.callbacks.codec import make, parse
from tests.helpers import OWNER, STRANGER, TempDirCase, buttons, cb_update, feed, make_bot_and_dp, make_hub, msg_update, texts


class OwnerOnlyTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.bot, self.dp, self.sess = make_bot_and_dp(self.hub)

    async def asyncTearDown(self):
        self.hub.db.close()
        await super().asyncTearDown()

    async def test_stranger_rejected_everywhere(self):
        await feed(self.bot, self.dp, msg_update("/start", uid=STRANGER))
        await feed(self.bot, self.dp, cb_update(make("p", "arch_ok", 1), uid=STRANGER))
        await feed(self.bot, self.dp, msg_update("/start", uid=STRANGER))  # second message: silent
        said = texts(self.sess)
        self.assertEqual(said, ["⛔ Ye private bot hai."])
        denied = self.hub.db.all("SELECT * FROM audit_events WHERE action = 'unauthorized'")
        self.assertEqual(len(denied), 3)

    async def test_setup_mode_tells_id_but_does_nothing(self):
        self.hub.settings.owner_id = 0
        bot, dp, sess = make_bot_and_dp(self.hub)
        await feed(bot, dp, msg_update("/start", uid=STRANGER))
        self.assertIn(f"OWNER_ID={STRANGER}", texts(sess)[0])
        self.assertEqual(self.hub.projects.list_projects()[1], 0)

    async def test_forged_and_stale_callbacks(self):
        for data in ("p|open|1", "v0|p|open|1", "v1|p|open|../../x", "v1|p|open|999", "v1|zz|yy", "x" * 70):
            await feed(self.bot, self.dp, cb_update(data))
        alerts = [m.text for n, m in self.sess.calls if n == "AnswerCallbackQuery" and m.text]
        self.assertTrue(alerts)
        self.assertTrue(all("purana" in a or "nahi mila" in a for a in alerts), alerts)
        self.assertIsNone(parse("v1|p|open|a b"))

    async def test_cloud_enable_needs_fresh_confirmation(self):
        await feed(self.bot, self.dp, cb_update(make("s", "cloud_ok", "forgedtoken")))
        self.assertFalse(self.hub.cloud_enabled)
        await feed(self.bot, self.dp, cb_update(make("s", "cloud", "ask")))
        ok = [b for b in buttons(self.sess) if b.startswith("v1|s|cloud_ok|")][0]
        await feed(self.bot, self.dp, cb_update(ok))
        self.assertTrue(self.hub.cloud_enabled)
        await feed(self.bot, self.dp, cb_update(ok))  # replay of the same button does nothing new
        self.assertEqual(len(self.hub.db.all("SELECT * FROM audit_events WHERE action = 'cloud_enable' AND result = 'ok'")), 1)

    async def test_owner_ok(self):
        await feed(self.bot, self.dp, msg_update("/start", uid=OWNER))
        self.assertIn("Video Production Hub", texts(self.sess)[-1])
