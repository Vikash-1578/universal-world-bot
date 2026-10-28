"""Character Studio + casting through Telegram buttons (fake Telegram session)."""
from app.telegram.callbacks.codec import make
from tests.helpers import TempDirCase, buttons, cb_update, feed, make_bot_and_dp, make_hub, msg_update, texts
from tests.unit.test_script_storyboard import SCRIPT


class LibraryFlowTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.hub.imagegen.url = "http://127.0.0.1:9"  # no ComfyUI in tests
        self.bot, self.dp, self.sess = make_bot_and_dp(self.hub)

    async def asyncTearDown(self):
        await self.hub.jobs.stop(grace=1)
        self.hub.db.close()
        await super().asyncTearDown()

    async def test_studio_and_templates(self):
        await feed(self.bot, self.dp, cb_update(make("m", "characters")))
        self.assertIn("Ready templates:", texts(self.sess)[-1])
        self.assertIn("band", texts(self.sess)[-1])  # ComfyUI honestly reported as off
        await feed(self.bot, self.dp, cb_update(make("lb", "tcat", "c")))
        cat_btn = [b for b in buttons(self.sess) if b.startswith("v1|lb|tl|c|")][0]
        await feed(self.bot, self.dp, cb_update(cat_btn))
        tv = [b for b in buttons(self.sess) if b.startswith("v1|lb|tv|")][0]
        await feed(self.bot, self.dp, cb_update(tv))
        await feed(self.bot, self.dp, cb_update(make("lb", "use", tv.split("|")[3])))
        rows, total = self.hub.library.list_items("character")
        self.assertEqual(total, 1)
        await feed(self.bot, self.dp, cb_update(make("lb", "new", "c")))
        await feed(self.bot, self.dp, msg_update("Golu Khargosh\nchhota safed khargosh, laal topi"))
        it = self.hub.library.get("golu-khargosh")
        self.assertEqual(it["profile"]["description"], "chhota safed khargosh, laal topi")
        await feed(self.bot, self.dp, cb_update(make("lb", "aiimg", it["id"])))
        self.assertIn("ComfyUI", texts(self.sess)[-1])  # honest message, no job submitted
        self.assertEqual(self.hub.jobs.list_jobs(), [])
        await feed(self.bot, self.dp, cb_update(make("lb", "qcok", it["id"])))
        self.assertIn("main image", self.sess.calls[-1][1].text)  # cannot approve without an image
        await feed(self.bot, self.dp, cb_update(make("lb", "find", "c")))
        await feed(self.bot, self.dp, msg_update("doctor"))
        self.assertIn("templates", texts(self.sess)[-1])

    async def test_casting_from_script(self):
        pid = self.hub.projects.create_project("Race", "2d")["id"]
        v = self.hub.scripts.create_version(pid, SCRIPT)
        self.hub.scripts.approve(v["id"])
        await feed(self.bot, self.dp, cb_update(make("lb", "cast", pid)))
        t = texts(self.sess)[-1]
        for role in ("Khargosh", "Sher", "Kachhua", "Jungle ka race track"):
            self.assertIn(role, t)
        await feed(self.bot, self.dp, cb_update(make("lb", "role", pid, 1)))  # Sher
        tmpl = [b for b in buttons(self.sess) if b.startswith("v1|lb|assignt|")]
        self.assertTrue(tmpl)  # catalog has a lion template
        await feed(self.bot, self.dp, cb_update(tmpl[0]))
        await feed(self.bot, self.dp, cb_update(make("lb", "assignn", pid, 0)))  # new item for Khargosh
        cast = self.hub.library.casting(pid)
        self.assertEqual(set(cast), {"Sher", "Khargosh"})
        self.assertEqual(cast["Khargosh"]["kind"], "character")
        await feed(self.bot, self.dp, cb_update(make("lb", "assignn", pid, 3)))  # place -> environment
        self.assertEqual(self.hub.library.casting(pid)["Jungle ka race track"]["kind"], "environment")
        await feed(self.bot, self.dp, cb_update(make("lb", "unassign", pid, 1)))
        self.assertNotIn("Sher", self.hub.library.casting(pid))
