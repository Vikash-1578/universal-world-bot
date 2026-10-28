"""Telegram dashboard flows with a fake Telegram session (test double) + real database / scheduler / FFmpeg."""
import asyncio

from app.scheduler import service as S
from app.telegram.callbacks.codec import make
from app.telegram.keyboards.menus import MAIN
from tests.helpers import TempDirCase, buttons, cb_update, feed, make_bot_and_dp, make_hub, msg_update, needs_ffmpeg, texts


class DashboardTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.bot, self.dp, self.sess = make_bot_and_dp(self.hub)

    async def asyncTearDown(self):
        await self.hub.jobs.stop(grace=1)
        self.hub.db.close()
        await super().asyncTearDown()

    async def test_main_menu_has_all_sections(self):
        await feed(self.bot, self.dp, msg_update("/menu"))
        got = buttons(self.sess)
        self.assertEqual(len(got), len(MAIN))
        await feed(self.bot, self.dp, cb_update(make("m", "animation")))
        self.assertIn("Milestone 6", texts(self.sess)[-1])

    async def test_create_open_rename_settings_version_archive(self):
        await feed(self.bot, self.dp, cb_update(make("m", "new")))
        await feed(self.bot, self.dp, cb_update(make("p", "type", "2d")))
        await feed(self.bot, self.dp, msg_update("Kachhua Khargosh Race"))
        rows, total = self.hub.projects.list_projects()
        self.assertEqual((total, rows[0]["name"]), (1, "Kachhua Khargosh Race"))
        pid = rows[0]["id"]
        self.assertTrue((self.hub.settings.data_dir / "projects" / str(pid) / "manifest.json").exists())
        await feed(self.bot, self.dp, cb_update(make("p", "opt", pid, "aspect", "9x16")))
        self.assertEqual(self.hub.projects.get_project(pid)["settings"]["aspect"], "9:16")
        await feed(self.bot, self.dp, cb_update(make("p", "rename", pid)))
        await feed(self.bot, self.dp, msg_update("Race 2.0"))
        self.assertEqual(self.hub.projects.get_project(pid)["name"], "Race 2.0")
        await feed(self.bot, self.dp, cb_update(make("p", "save", pid)))
        vs = self.hub.projects.versions(pid)
        self.assertEqual(len(vs), 2)
        self.assertTrue(self.hub.projects.verify_version(vs[0]["id"]))
        await feed(self.bot, self.dp, cb_update(make("p", "arch", pid)))
        self.assertIsNone(self.hub.projects.get_project(pid)["archived_at"])  # needs confirmation
        await feed(self.bot, self.dp, cb_update(make("p", "arch_ok", pid)))
        self.assertIsNotNone(self.hub.projects.get_project(pid)["archived_at"])

    async def test_conversation_survives_restart(self):
        await feed(self.bot, self.dp, cb_update(make("p", "type", "3d")))
        hub2 = make_hub(self.tmp)  # new process, same database
        bot2, dp2, sess2 = make_bot_and_dp(hub2)
        await feed(bot2, dp2, msg_update("Blender Demo"))
        self.assertEqual(hub2.projects.list_projects()[0][0]["project_type"], "3d")
        hub2.db.close()

    async def test_bad_project_name(self):
        await feed(self.bot, self.dp, cb_update(make("p", "type", "2d")))
        await feed(self.bot, self.dp, msg_update("x"))
        self.assertIn("2 akshar", texts(self.sess)[-1])

    @needs_ffmpeg
    async def test_selftest_job_real_ffmpeg_and_card(self):
        await feed(self.bot, self.dp, cb_update(make("d", "selftest"), message_id=77))
        await feed(self.bot, self.dp, cb_update(make("d", "selftest"), message_id=77))  # double tap
        jobs = self.hub.jobs.list_jobs()
        self.assertEqual(len(jobs), 1)
        await self.hub.jobs.wait_idle(timeout=120)
        await asyncio.sleep(0.05)
        j = self.hub.jobs.get_job(jobs[0]["id"])
        self.assertEqual(j["status"], S.COMPLETED, j["error_message"])
        self.assertIn('"duration"', j["output_manifest"])
        edits = [m for n, m in self.sess.calls if n == "EditMessageText" and "Job #" in (m.text or "")]
        self.assertTrue(edits)  # live card was updated
        self.assertTrue(any("ho gaya" in t for t in texts(self.sess, "SendMessage")))
