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

    async def test_casting_empty_items_warn_and_ai_all(self):
        """Items made from a script name have no picture: casting must say so, and one button makes them all.
        The image AI here is a TEST DOUBLE (returns a drawn figure) — it proves the flow, not image quality."""
        from tests.unit.test_library import background, figure_on_green

        pid = self.hub.projects.create_project("Race", "2d")["id"]
        v = self.hub.scripts.create_version(pid, SCRIPT)
        self.hub.scripts.approve(v["id"])
        await feed(self.bot, self.dp, cb_update(make("lb", "assignn", pid, 0)))  # Khargosh -> empty item
        await feed(self.bot, self.dp, cb_update(make("lb", "assignn", pid, 3)))  # place -> empty environment
        t = texts(self.sess)[-1]
        self.assertIn("image nahi", t)
        self.assertNotIn("✅", t.split("Khargosh")[1].split("\n")[0])
        self.assertIn(make("lb", "aiall", pid), buttons(self.sess))

        class FakeImages:
            last_provider = "fake"

            async def available(self):
                return True

            async def generate(self, prompt, width=0, height=0, progress=None, **kw):
                return background() if width > height else figure_on_green()

        self.hub.imagegen = FakeImages()
        await feed(self.bot, self.dp, cb_update(make("lb", "aiall", pid)))
        self.assertIn("2 AI image jobs", texts(self.sess)[-1])
        await self.hub.jobs.start()
        await self.hub.jobs.wait_idle(timeout=60)
        cast = self.hub.library.casting(pid)
        self.assertEqual(cast["Khargosh"]["version"], 2)  # re-cast to the new picture automatically
        self.assertFalse(cast["Khargosh"]["outdated"])
        from app.telegram.handlers.library import missing_images

        self.assertEqual(missing_images(self.hub, pid), {})

    async def test_bulk_template_images_resume_and_limit(self):
        """Bulk AI pictures for ready templates. Image AI is a TEST DOUBLE: works 3 times, then says 'daily limit'."""
        from app.characters import bulk
        from app.core.errors import ProviderUnavailable
        from tests.unit.test_library import background, figure_on_green

        ids = bulk.template_ids("featured")
        self.assertEqual(len(ids), 48 + 97)
        calls = {"n": 0}

        class FakeImages:
            last_provider = "fake"

            async def available(self):
                return True

            async def generate(self, prompt, width=0, height=0, **kw):
                calls["n"] += 1
                if calls["n"] > 3:
                    raise ProviderUnavailable("Cloudflare key / daily limit problem.")
                return background() if width > height else figure_on_green()

        self.hub.imagegen = FakeImages()
        await feed(self.bot, self.dp, cb_update(make("lb", "bulk")))
        self.assertIn("0/145", texts(self.sess)[-1])
        await feed(self.bot, self.dp, cb_update(make("lb", "bulkok")))
        await self.hub.jobs.start()
        await self.hub.jobs.wait_idle(timeout=60)
        job = [j for j in self.hub.jobs.list_jobs(limit=20) if j["job_type"] == bulk.JOB][0]
        out = self.hub.jobs.get_job(job["id"])
        self.assertEqual(out["status"], "completed")
        self.assertIn('"made": 3', out["output_manifest"])
        self.assertIn("limit", out["output_manifest"])
        self.assertEqual(bulk.progress(self.hub)[0], 3)
        # next day: limit gone -> a new run continues, the 3 done ones are not made again
        calls["n"] = -1000
        before = calls["n"]
        await feed(self.bot, self.dp, cb_update(make("lb", "bulkok"), message_id=77))
        await self.hub.jobs.wait_idle(timeout=120)
        self.assertEqual(bulk.progress(self.hub), (145, 145))
        self.assertEqual(calls["n"] - before, 145 - 3)
        # casting from a template reuses the item that already has the picture (no empty copy)
        first = self.hub.library.find_by_template(ids[0])
        n_items = self.hub.db.one("SELECT COUNT(*) AS n FROM library_items")["n"]
        await feed(self.bot, self.dp, cb_update(make("lb", "use", ids[0])))
        self.assertEqual(self.hub.db.one("SELECT COUNT(*) AS n FROM library_items")["n"], n_items)
        self.assertTrue(bulk.has_picture(first))
