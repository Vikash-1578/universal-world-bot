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

    async def test_choose_each_role_library_template_ai(self):
        from app.characters import templates
        from app.telegram.handlers.library import project_roles

        self.assertTrue(templates.search("चिंटू खरगोश", "actor"))  # Hindi story words find ready templates
        self.assertTrue(templates.search("नदी किनारा", "place"))
        pid = self.hub.projects.create_project("Race", "2d")["id"]
        v = self.hub.scripts.create_version(pid, SCRIPT)
        await feed(self.bot, self.dp, cb_update(make("w", "okstory", pid, v["id"])))
        roles = project_roles(self.hub, pid)
        i_k = next(i for i, (_k, r) in enumerate(roles) if r == "Khargosh")
        self.assertIn(make("w", "role", pid, i_k), buttons(self.sess))  # every role has its own ✏️ button
        await feed(self.bot, self.dp, cb_update(make("w", "role", pid, i_k)))
        self.assertTrue({make("w", "lib", pid, i_k, 0), make("w", "tpl", pid, i_k), make("w", "ai1", pid, i_k),
                         make("w", "own", pid, i_k)} <= set(buttons(self.sess)))
        # 1) ready template
        await feed(self.bot, self.dp, cb_update(make("w", "tpl", pid, i_k)))
        tp = [b for b in buttons(self.sess) if b.startswith("v1|w|tpick|")]
        self.assertTrue(tp)
        await feed(self.bot, self.dp, cb_update(tp[0]))
        tid = tp[0].split("|")[-1]
        cast = self.hub.library.casting(pid)["Khargosh"]
        self.assertEqual(self.hub.library.get(cast["item_id"])["template_id"], tid)
        self.assertIn(make("w", "ai1", pid, i_k), buttons(self.sess))  # template has no picture yet -> offers AI
        # 2) own library item that already has a picture
        own = self.hub.library.create_item("character", "Golu")
        self.hub.library.add_image(own["id"], "main", figure_on_green())
        await feed(self.bot, self.dp, cb_update(make("w", "lib", pid, i_k, 0)))
        self.assertIn(make("w", "pick", pid, i_k, own["id"]), buttons(self.sess))
        await feed(self.bot, self.dp, cb_update(make("w", "pick", pid, i_k, own["id"])))
        self.assertEqual(self.hub.library.casting(pid)["Khargosh"]["item_id"], own["id"])
        self.assertIn("✅ 🧍 Khargosh → Golu", texts(self.sess)[-1])
        # 3) AI for one role only
        await feed(self.bot, self.dp, cb_update(make("w", "ai1", pid, i_k)))
        jobs = [j for j in self.hub.jobs.list_jobs(limit=50) if j["job_type"] == "library_ai_image"]
        self.assertEqual(len(jobs), 1)
        # 4) own picture: bot waits for an image for this role (upload itself covered by library tests)
        await feed(self.bot, self.dp, cb_update(make("w", "own", pid, i_k)))
        st = self.hub.extra["conv"].get(1001)
        self.assertEqual((st["step"], st["data"]["recast"]["role"]), ("lib_img", "Khargosh"))

    async def test_role_context_tells_the_ai_what_a_name_is(self):
        from app.telegram.handlers.wizard import role_context

        pid = self.hub.projects.create_project("Chintu", "2d")["id"]
        self.hub.scripts.create_version(pid, "Title: चिंटू की जल्दबाज़ी\n[Scene 1: जंगल, सुबह]\n"
                                             "Narrator: हरे-भरे जंगल में चिंटू नाम का एक तेज़ खरगोश रहता था।\nचिंटू: (खुश) आज मैं जीतूँगा!\n")
        ctx = role_context(self.hub, pid, "चिंटू")
        self.assertIn("खरगोश", ctx)  # the species comes from the narration, not from the name
        self.assertIn("आज मैं जीतूँगा", ctx)
