"""Milestone 6: storyboard + casting -> plan -> real FFmpeg render -> validated export, restart reuse, approval gate,
Telegram screens. Pictures are generated with Pillow in the test; the renderer and FFmpeg are REAL (no mocks)."""
import asyncio
import io

from PIL import Image

from app.animation.two_d import jobs as anim_jobs
from app.animation.two_d import planner, puppet
from app.animation.two_d.rig import Rig
from app.core.errors import Conflict
from app.telegram.callbacks.codec import make
from tests.helpers import OWNER, STRANGER, FakeTTS, TempDirCase, buttons, cb_update, feed, make_bot_and_dp, make_hub, needs_ffmpeg, texts
from tests.unit.test_library import background, figure_on_green
from tests.unit.test_script_storyboard import SCRIPT

SHORT = """Title: Chhoti kahani

[Scene 1: Jungle, subah]
Khargosh: (khush ho kar) Namaste dost!
Kachhua: Namaste!

[Scene 2: Jungle, raat]
Narrator: Raat ho gayi.
"""


class PlannerUnitTests(TempDirCase):
    async def test_mappings(self):
        self.assertEqual(planner.emotion_of("gusse me"), "angry")
        self.assertEqual(planner.emotion_of("डर के"), "scared")
        self.assertEqual(planner.emotion_of(""), "")
        self.assertEqual(planner.action_of("haath hila ke"), "wave")
        self.assertEqual(planner.mood_of("night, moonlight", "Jungle"), "night")
        self.assertEqual(planner.mood_of("bright daylight", "Raju ka ghar"), "indoor")
        self.assertEqual(planner.camera_of("slow zoom in"), "zoom_in")
        self.assertEqual(planner.frame_size("16:9", 360), (640, 360))
        self.assertEqual(planner.frame_size("9:16", 1080), (1080, 1920))
        self.assertEqual(planner.frame_size("1:1", 360), (360, 360))
        self.assertGreater(planner.line_seconds("ek do teen char paanch chhe saat aath nau das"), planner.line_seconds("haan"))

    async def test_rig_and_frame(self):
        fig = Image.open(io.BytesIO(figure_on_green()))
        from app.characters import imaging

        cut = imaging.cutout(fig)
        rig = Rig(cut, {})
        self.assertTrue(rig.has_legs())
        self.assertGreater(rig.compose(leg=2).getbbox()[2], 0)
        ph = cut.transpose(Image.FLIP_LEFT_RIGHT)  # test-only second actor (drawn in the test, not by the app)
        sky = Image.open(io.BytesIO(background())).convert("RGB")
        sc = puppet.PuppetScene(background=sky,
                                actors=[puppet.Actor("A", cut, x=0.3, enter="left"), puppet.Actor("B", ph, x=0.7)],
                                talks=[puppet.Talk("A", 0.5, 1.5, "happy", "jump")], duration=2.0, camera="zoom_in")
        frame = puppet.preview(sc, 320, 180, 1.0)
        self.assertEqual(frame.size, (320, 180))
        self.assertEqual(frame.mode, "RGB")
        self.assertFalse(hasattr(planner, "placeholder_figure"))  # no stand-in renderer left in the app

    async def test_load_scene_refuses_missing_pictures(self):
        hub = make_hub(self.tmp)
        try:
            sc = {"n": 2, "background": {"place": "Jungle"}, "actors": [{"id": "Sher", "x": 0.5}], "talks": [],
                  "duration": 2.0, "camera": "static", "mood": "day", "fade": False}
            with self.assertRaises(Conflict) as cm:
                planner.load_scene(hub, sc, 12)
            self.assertIn("Jungle", cm.exception.user_message)
            self.assertIn("Sher", cm.exception.user_message)
        finally:
            hub.db.close()


class AnimationFlowTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.hub.tts = FakeTTS()
        self.pid = self.hub.projects.create_project("Race", "2d")["id"]

    async def asyncTearDown(self):
        await self.hub.jobs.stop()
        self.hub.db.close()
        await super().asyncTearDown()

    async def _storyboard(self, script=SHORT, approve=False):
        v = self.hub.scripts.create_version(self.pid, script)
        self.hub.scripts.approve(v["id"])
        await self.hub.storyboards.generate_draft(self.pid, use_ai=False)
        if approve:
            self.hub.storyboards.approve(self.pid)

    def _cast_all(self):
        lib = self.hub.library
        k = lib.create_item("character", "Golu")
        lib.add_image(k["id"], "main", figure_on_green())
        lib.cast(self.pid, "Khargosh", k["id"])
        t = lib.create_item("character", "Tortu")
        lib.add_image(t["id"], "main", figure_on_green(bg=(255, 255, 255)))
        lib.cast(self.pid, "Kachhua", t["id"])
        e = lib.create_item("environment", "Jungle")
        lib.add_image(e["id"], "background", background())
        lib.cast(self.pid, "Jungle", e["id"])

    async def test_plan_warnings_and_casting(self):
        with self.assertRaises(Conflict):
            planner.build(self.hub, self.pid)  # no storyboard yet
        await self._storyboard(SCRIPT)
        plan = planner.build(self.hub, self.pid, "preview")
        self.assertEqual(len(plan["scenes"]), 3)
        self.assertEqual((plan["width"], plan["height"], plan["fps"]), (640, 360, 12))
        self.assertTrue(any("Khargosh" in w for w in plan["warnings"]))
        sc1 = plan["scenes"][0]
        self.assertEqual([a["id"] for a in sc1["actors"]], ["Khargosh", "Sher"])
        self.assertEqual(sc1["talks"][0]["emotion"], "angry")
        self.assertTrue(all(a.get("enter") for a in sc1["actors"]))
        self.assertFalse(any(a.get("enter") for a in plan["scenes"][2]["actors"] if a["id"] == "Sher"))  # already on stage
        self.assertGreaterEqual(sc1["duration"], sc1["talks"][-1]["end"])
        self.assertEqual(plan, planner.build(self.hub, self.pid, "preview"))  # deterministic
        with self.assertRaises(Conflict):
            anim_jobs.start(self.hub, self.pid, "final")  # storyboard not approved -> final blocked
        p3 = self.hub.projects.create_project("Teen D test", "3d")["id"]
        with self.assertRaises(Conflict) as c3:
            anim_jobs.start(self.hub, p3, "preview")  # separate 3D project never goes through the 2D renderer
        self.assertIn("2D nahi", c3.exception.user_message)
        with self.assertRaises(Conflict) as cm:
            anim_jobs.start(self.hub, self.pid, "preview")  # no stand-in 'putla': missing pictures block every render
        self.assertIn("image nahi", cm.exception.user_message)

    @needs_ffmpeg
    async def test_render_validate_export_and_resume(self):
        await self._storyboard(SHORT, approve=True)
        self._cast_all()
        plan = planner.build(self.hub, self.pid, "preview")
        self.assertFalse([w for w in plan["warnings"] if "Khargosh" in w or "Jungle" in w])
        self.assertTrue(plan["scenes"][0]["actors"][0].get("main"))
        bot, dp, sess = make_bot_and_dp(self.hub)  # fake Telegram (test double) to see the finished video being sent
        job = anim_jobs.start(self.hub, self.pid, "preview", chat_id=OWNER)
        await self.hub.jobs.start()
        await self.hub.jobs.wait_idle(timeout=240)
        j = self.hub.jobs.get_job(job["id"])
        self.assertEqual(j["status"], "completed", j["error_message"])
        outs = anim_jobs.exports(self.hub, self.pid)
        self.assertEqual(len(outs), 1)
        meta = outs[0]["meta"]
        self.assertEqual((meta["width"], meta["height"], meta["fps"], meta["scenes"]), (640, 360, 12, 2))
        self.assertTrue(outs[0]["abs"].exists())
        await asyncio.sleep(0.2)
        self.assertIn("SendVideo", [n for n, _ in sess.calls])
        from app.exports.validate import check, probe

        info = await probe(self.hub.settings, outs[0]["abs"])
        self.assertEqual(check(info, width=640, height=360, fps=12), [])
        self.assertFalse(meta["silent_audio"])  # real voice track, not the old silent one
        self.assertEqual(meta["lines"], 3)  # 2 dialogue lines + 1 narrator line in SHORT
        self.assertTrue((self.hub.settings.data_dir / meta["subtitles"]).exists())
        man = self.hub.projects.manifest(self.pid)
        self.assertEqual([e["kind"] for e in man["exports"]], ["preview"])  # export listed in the project manifest
        # restart/retry: finished scene checkpoints are reused, not re-rendered
        stages = {s["stage_name"]: s for s in self.hub.jobs.stages(job["id"])}
        self.assertIn("scene_1", stages)
        before = (self.hub.jobs.work_root / f"job_{job['id']}" / "scene_001.mp4").stat().st_mtime_ns
        self.hub.db.execute("UPDATE jobs SET status = 'failed' WHERE id = ?", (job["id"],))
        self.hub.db.execute("DELETE FROM job_stages WHERE job_id = ? AND stage_name IN ('export', 'validate', 'join')", (job["id"],))
        self.hub.jobs.retry_job(job["id"])
        await self.hub.jobs.wait_idle(timeout=240)
        self.assertEqual(self.hub.jobs.get_job(job["id"])["status"], "completed")
        after = (self.hub.jobs.work_root / f"job_{job['id']}" / "scene_001.mp4").stat().st_mtime_ns
        self.assertEqual(before, after)
        self.assertEqual(len(anim_jobs.exports(self.hub, self.pid)), 2)


class AnimationTelegramTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.hub.tts = FakeTTS()
        self.bot, self.dp, self.sess = make_bot_and_dp(self.hub)
        self.pid = self.hub.projects.create_project("Race", "2d")["id"]

    async def asyncTearDown(self):
        self.hub.db.close()
        await super().asyncTearDown()

    async def test_screens_and_owner_only(self):
        await feed(self.bot, self.dp, cb_update(make("m", "animation")))
        self.assertIn("Kis project", texts(self.sess)[-1])
        await feed(self.bot, self.dp, cb_update(make("an", "open", self.pid)))
        self.assertIn("Storyboard banao", texts(self.sess)[-1])
        v = self.hub.scripts.create_version(self.pid, SHORT)
        self.hub.scripts.approve(v["id"])
        await self.hub.storyboards.generate_draft(self.pid, use_ai=False)
        await feed(self.bot, self.dp, cb_update(make("an", "open", self.pid)))
        t = texts(self.sess)[-1]
        self.assertIn("Scenes: 2", t)
        self.assertIn("🎤 Awaaz: fake-voice", t)
        self.assertIn(make("an", "go", self.pid, "preview"), buttons(self.sess))
        await feed(self.bot, self.dp, cb_update(make("an", "go", self.pid, "final")))  # draft -> blocked with an alert
        self.assertEqual(self.hub.jobs.list_jobs(project_id=self.pid), [])
        await feed(self.bot, self.dp, cb_update(make("an", "go", self.pid, "preview")))  # nothing cast -> blocked
        self.assertEqual(self.hub.jobs.list_jobs(project_id=self.pid), [])
        AnimationFlowTests._cast_all(self)
        await feed(self.bot, self.dp, cb_update(make("an", "go", self.pid, "preview"), uid=STRANGER))
        self.assertEqual(self.hub.jobs.list_jobs(project_id=self.pid), [])  # stranger blocked by the owner gate
        await feed(self.bot, self.dp, cb_update(make("an", "go", self.pid, "preview")))
        jobs = self.hub.jobs.list_jobs(project_id=self.pid)
        self.assertEqual([j["job_type"] for j in jobs], ["anim_2d"])
        await feed(self.bot, self.dp, cb_update(make("an", "still", self.pid)))
        self.assertIn("SendPhoto", [n for n, _ in self.sess.calls])
        await feed(self.bot, self.dp, cb_update(make("an", "out", self.pid)))
        self.assertIn("Abhi koi video nahi", texts(self.sess)[-1])


class EmotionFromWordsTests(TempDirCase):
    async def test_line_words_give_the_face_when_no_bracket(self):
        hub = make_hub(self.tmp)
        try:
            pid = hub.projects.create_project("Emo", "2d")["id"]
            v = hub.scripts.create_version(pid, "Title: T\n[Scene 1: Jungle, subah]\nGolu: Arre baap re, ye kya hua!\nTortu: (khush) Chalo!\n")
            hub.scripts.approve(v["id"])
            await hub.storyboards.generate_draft(pid, use_ai=False)
            plan = planner.build(hub, pid)
            emos = [t["emotion"] for t in plan["scenes"][0]["talks"]]
            self.assertEqual(emos, ["", "happy"])  # Latin 'baap re' is not in the list; bracket wins for Tortu
            v2 = hub.scripts.create_version(pid, "Title: T\n[Scene 1: Jungle, subah]\nगोलू: अरे बाप रे, ये क्या हुआ!\n")
            hub.scripts.approve(v2["id"])
            await hub.storyboards.generate_draft(pid, use_ai=False, replace_approved=True)
            self.assertEqual(planner.build(hub, pid)["scenes"][0]["talks"][0]["emotion"], "scared")  # from the words
        finally:
            hub.db.close()
