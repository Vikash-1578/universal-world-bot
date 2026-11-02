"""Manager chat: the owner's only entry point. AI is a TEST DOUBLE (FakeLLM)."""
import json

from app.agents.team import TEAM, team_text
from tests.helpers import TempDirCase, make_hub
from tests.unit.test_agents import FakeWeb, SmartLLM
from tests.unit.test_agents import FakeWeb, SmartLLM
from tests.unit.test_scripts import FakeLLM

UID, CHAT = 1001, 1001


class ManagerChatTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.m = self.hub.manager

    async def asyncTearDown(self):
        await self.hub.jobs.stop(grace=1)
        self.hub.db.close()
        await super().asyncTearDown()

    def use(self, replies=None, ok=True, smart=False):
        if smart:
            self.hub.llm = self.hub.scripts.llm = SmartLLM()
            self.hub.web = FakeWeb()
            return self.hub.llm
        self.hub.llm = self.hub.scripts.llm = FakeLLM(replies, ok=ok)
        return self.hub.llm

    async def say(self, text, mid=1):
        return await self.m.handle(UID, CHAT, text, message_id=mid)

    async def test_team_is_fifteen_roles(self):
        self.assertEqual(len(TEAM), 15)
        self.assertIn("15. Config", team_text())
        self.assertIn("Manager", await self.say("team"))

    async def test_new_video_needs_confirmation_then_runs(self):
        self.use(smart=True)
        r = await self.say("naya video: Bermuda Triangle ke raaz")
        self.assertIn("Shuru karun", r)
        self.assertEqual(self.hub.jobs.list_jobs(), [])  # nothing runs before haan
        r = await self.say("haan", mid=2)
        self.assertIn("Shuru", r)
        await self.hub.jobs.wait_idle(timeout=20)
        job = self.hub.jobs.list_jobs()[0]
        self.assertEqual(job["status"], "completed", job["error_message"])
        self.assertEqual(self.hub.scripts.latest(self.m.project_id)["approval_status"], "draft")

    async def test_no_cancels_and_unclear_reply_asks_again(self):
        self.use()
        await self.say("naya video: Mariana Trench ka sach")
        self.assertIn("haan ya nahi", await self.say("pata nahi kya bolun", mid=2))
        self.assertIn("kuch nahi kiya", await self.say("nahi", mid=3))
        self.assertEqual(self.hub.jobs.list_jobs(), [])
        self.assertEqual(self.hub.projects.list_projects()[1], 0)

    async def test_approve_only_after_haan(self):
        self.use(smart=True)
        await self.say("naya video: Bermuda Triangle ke raaz")
        await self.say("haan", mid=2)
        await self.hub.jobs.wait_idle(timeout=20)
        self.assertIn("approve karun", await self.say("approve", mid=3))
        self.assertIsNone(self.hub.scripts.approved(self.m.project_id))
        self.assertIn("approved", await self.say("haan", mid=4))
        self.assertIsNotNone(self.hub.scripts.approved(self.m.project_id))

    async def test_llm_understands_free_text_and_ai_off_falls_back_to_help(self):
        self.use([json.dumps({"intent": "new_video", "topic": "Pyramids kaise bane the", "instruction": ""})])
        self.assertIn("Pyramids kaise bane the", await self.say("yaar pyramids pe kuch banao na"))
        await self.say("nahi", mid=2)
        self.use(ok=False)
        self.assertIn("status", await self.say("kuch bhi random"))
        self.assertIn("AI abhi band", await self.say("naya video: Atlantis ka raaz", mid=3))

    async def test_status_idle_and_bad_llm_intent_is_ignored(self):
        self.use([json.dumps({"intent": "delete_everything", "topic": "x"}), "Theek hai, bata do."])
        self.assertEqual(await self.say("kuch ajeeb sa"), "Theek hai, bata do.")  # unknown intent -> plain chat
        self.assertIn("koi kaam nahi", await self.say("status"))
