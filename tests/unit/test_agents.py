"""Agents. The AI here is a TEST DOUBLE (FakeLLM): it proves our handling of AI output and the pipeline logic,
not that a real model's facts are correct."""
import json

from app.agents.factcheck import script_flags
from app.agents.research import normalise
from tests.helpers import TempDirCase, make_hub
from tests.unit.test_scripts import FakeLLM

POINTS = [{"point": f"Fact number {i} about the Bermuda Triangle", "confidence": "high"} for i in range(1, 6)] + [
    {"point": "Ships vanish because of aliens", "confidence": "low"},
    {"point": "A legend says Flight 19 was lost in 1945", "confidence": "medium", "disputed": True}]
RESEARCH = json.dumps({"summary": "s", "key_points": POINTS, "angles": ["a"], "avoid": ["aliens"]})
VERDICTS = json.dumps({"verdicts": [{"n": i, "verdict": "supported", "reason": "ok"} for i in range(1, 6)]
                       + [{"n": 6, "verdict": "likely_wrong", "reason": "no evidence"}, {"n": 7, "verdict": "uncertain", "reason": "legend"}]})
GOOD = """Title: Bermuda Triangle ka raaz
[Scene 1: Hook]
(show: stormy ocean)
Narrator: Kya ek poora jahaz bina nishaan ke gayab ho sakta hai?
[Scene 2: Kahani]
(show: map of the Atlantic)
Narrator: Fact number 1 ke baare me log kam jaante hain.
[Scene 3: Flight 19]
(show: old aircraft photo)
Narrator: Kehte hain Flight 19 kho gayi thi, par ye ek legend hai.
[Scene 4: Science]
(show: ocean currents)
Narrator: Fact number 3 samjhata hai ki samundar tez badalta hai.
[Scene 5: Ant]
(show: sunset sea)
Narrator: Isliye sawal ab bhi dilchasp hai.
"""
BAD = GOOD.replace("Title: Bermuda Triangle ka raaz\n", "")  # no title -> error -> one revision


class AgentTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.pid = self.hub.projects.create_project("Bermuda", "slideshow")["id"]

    async def asyncTearDown(self):
        await self.hub.jobs.stop(grace=1)
        self.hub.db.close()
        await super().asyncTearDown()

    def use(self, replies):
        self.hub.llm = FakeLLM(replies)
        self.hub.scripts.llm = self.hub.llm
        return self.hub.llm

    async def run_job(self, topic="Bermuda Triangle ke raaz"):
        j = self.hub.jobs.submit_job("video_pipeline", self.pid, {"project_id": self.pid, "topic": topic})
        await self.hub.jobs.wait_idle(timeout=20)
        return self.hub.jobs.get_job(j["id"])

    async def test_normalise_never_trusts_model_json(self):
        d = normalise({"key_points": ["plain string", {"point": ""}, {"point": "x", "confidence": "SURE"}, 5], "angles": "bad"})
        self.assertEqual([p["confidence"] for p in d["key_points"]], ["low", "low"])
        self.assertEqual((d["angles"], d["basis"]), ([], "model_memory"))
        self.assertEqual(normalise("garbage")["key_points"], [])

    async def test_script_flags_unbacked_numbers_only_in_narration(self):
        text = "Title: T\n[Scene 1: A]\n(show: 1945 newsreel)\nNarrator: Flight 19 vanished in 1945 with 14 men.\n"
        flags = script_flags(text, "Flight 19 vanished in 1945")
        self.assertEqual([f["numbers"] for f in flags], [["14"]])

    async def test_pipeline_happy_path_drops_weak_facts_and_never_approves(self):
        llm = self.use([RESEARCH, VERDICTS, GOOD])
        row = await self.run_job()
        self.assertEqual(row["status"], "completed", row["error_message"])
        out = json.loads(row["output_manifest"])
        self.assertTrue(out["passed"])
        self.assertIsNone(self.hub.scripts.approved(self.pid))  # owner approves, never the agents
        self.assertIn("Fact number 1", llm.prompts[2])
        self.assertNotIn("aliens", llm.prompts[2])  # low-confidence / likely_wrong claim dropped
        self.assertNotIn("Flight 19 was lost in 1945", llm.prompts[2])  # uncertain + medium confidence -> dropped
        folder = self.hub.projects.folder(self.pid, "agents")
        self.assertTrue((folder / "research.json").exists() and (folder / "quality.json").exists())

    async def test_quality_failure_triggers_one_revision(self):
        self.use([RESEARCH, VERDICTS, BAD, GOOD])
        row = await self.run_job()
        self.assertEqual(row["status"], "completed", row["error_message"])
        out = json.loads(row["output_manifest"])
        self.assertTrue(out["passed"])
        self.assertEqual(out["version"], 2)
        self.assertIn("Auto-badlaav: 1", out["report"])

    async def test_too_few_facts_stops_pipeline_honestly(self):
        weak = json.dumps({"key_points": [{"point": "only one", "confidence": "high"}]})
        self.use([weak])
        row = await self.run_job()
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(self.hub.scripts.latest(self.pid))
