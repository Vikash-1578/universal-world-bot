"""🎬 Nayi video guided flow through Telegram buttons. Telegram, the AI writer and the image AI are TEST DOUBLES;
database, scheduler, casting and the job chain are real."""
from app.telegram.callbacks.codec import make
from tests.helpers import FakeTTS, TempDirCase, buttons, cb_update, feed, make_bot_and_dp, make_hub, msg_update, texts
from tests.unit.test_library import background, figure_on_green
from tests.unit.test_script_storyboard import SCRIPT, FakeLLM


class FakeImages:
    last_provider = "fake"

    async def available(self):
        return True

    async def sources(self):
        return {"comfyui": False, "cloudflare": True}

    async def generate(self, prompt, width=0, height=0, **kw):
        return background() if width > height else figure_on_green()


class WizardTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.hub.llm = FakeLLM()
        self.hub.scripts.llm = self.hub.storyboards.llm = self.hub.llm
        self.hub.imagegen = FakeImages()
        self.hub.tts = FakeTTS()
        self.bot, self.dp, self.sess = make_bot_and_dp(self.hub)

    async def asyncTearDown(self):
        await self.hub.jobs.stop(grace=1)
        self.hub.db.close()
        await super().asyncTearDown()

    async def test_paste_story_to_final_video_button(self):
        await feed(self.bot, self.dp, cb_update(make("m", "new")))
        self.assertIn(make("w", "type", "2d"), buttons(self.sess))
        await feed(self.bot, self.dp, cb_update(make("w", "type", "2d")))
        self.assertEqual(set(buttons(self.sess)) >= {make("w", "paste"), make("w", "file"), make("w", "ai")}, True)
        await feed(self.bot, self.dp, cb_update(make("w", "paste")))
        await feed(self.bot, self.dp, msg_update(SCRIPT))  # already in script format -> used directly, no AI call
        rows, _ = self.hub.projects.list_projects()
        pid = rows[0]["id"]
        self.assertEqual(rows[0]["name"], "Kachhua aur Khargosh 2.0")  # named from the story title, not asked
        self.assertIn("Step 1: Kahani", texts(self.sess)[-1])
        sid = self.hub.scripts.latest(pid)["id"]
        await feed(self.bot, self.dp, cb_update(make("w", "okstory", pid, sid)))
        self.assertTrue(self.hub.scripts.approved(pid))
        t = texts(self.sess)[-1]
        self.assertIn("Step 2", t)
        self.assertIn("image nahi", t)
        self.assertEqual(len(self.hub.library.casting(pid)), 6)  # every role + place auto-cast
        self.assertNotIn(make("w", "voice", pid), buttons(self.sess))  # cannot go on without pictures
        await feed(self.bot, self.dp, cb_update(make("w", "aiall", pid)))
        await self.hub.jobs.start()
        await self.hub.jobs.wait_idle(timeout=90)
        from app.telegram.handlers.wizard import missing_pictures, next_step

        self.assertEqual(missing_pictures(self.hub, pid), [])
        self.assertTrue(self.hub.storyboards.scenes(pid))  # storyboard drafted in the background
        self.assertIn("Step 2", texts(self.sess)[-1])  # notifier re-showed the screen when the last image finished
        self.assertIn(make("w", "voice", pid), buttons(self.sess))
        self.assertEqual(next_step(self.hub, pid), "check")
        await feed(self.bot, self.dp, cb_update(make("w", "check", pid)))
        self.assertIn(make("w", "final", pid), buttons(self.sess))
        await self.hub.jobs.stop(grace=1)  # don't actually render here (covered in test_animation_2d)
        await feed(self.bot, self.dp, cb_update(make("w", "final", pid)))
        self.assertEqual(self.hub.storyboards.state(pid)["status"], "approved")
        self.assertIn("anim_2d", [j["job_type"] for j in self.hub.jobs.list_jobs(project_id=pid, limit=50)])

    async def test_ai_story_with_genre_and_length(self):
        await feed(self.bot, self.dp, cb_update(make("w", "ai")))
        self.assertIn(make("w", "genre", "comedy"), buttons(self.sess))
        await feed(self.bot, self.dp, cb_update(make("w", "genre", "comedy")))
        await feed(self.bot, self.dp, cb_update(make("w", "len", "comedy", 60)))
        await feed(self.bot, self.dp, msg_update("Golu khargosh jo sabse tez daudna chahta hai"))
        await self.hub.jobs.start()
        await self.hub.jobs.wait_idle(timeout=30)
        self.assertIn("funny", self.hub.llm.prompts[0])
        self.assertIn("Golu khargosh", self.hub.llm.prompts[0])
        rows, _ = self.hub.projects.list_projects()
        self.assertEqual(rows[0]["name"], "Kachhua aur Khargosh 2.0")
        self.assertIn("Step 1: Kahani", texts(self.sess)[-1])  # next screen sent automatically

    async def test_prose_story_goes_through_ai(self):
        await feed(self.bot, self.dp, cb_update(make("w", "paste")))
        await feed(self.bot, self.dp, msg_update("Ek jungle me ek chhota khargosh rehta tha. Wo bahut tez daudta tha aur sabko chidhata tha."))
        await self.hub.jobs.start()
        await self.hub.jobs.wait_idle(timeout=30)
        self.assertIn("STORY:", self.hub.llm.prompts[0])
        self.assertIn("Step 1: Kahani", texts(self.sess)[-1])
