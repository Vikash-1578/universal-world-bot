import asyncio
import time

from app.core.errors import Conflict, HubError, Recoverable
from app.scheduler import service as S
from tests.helpers import TempDirCase, make_hub


class SchedulerTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.js = self.hub.jobs
        self.log: list[str] = []

    async def asyncTearDown(self):
        await self.js.stop(grace=1)
        self.hub.db.close()
        await super().asyncTearDown()

    def reg(self, name, fn, **kw):
        self.js.register(name, fn, **kw)

    async def test_priority_dependencies_and_stages(self):
        async def work(ctx):
            self.log.append(ctx.inputs["n"])
            async with ctx.stage("a", ctx.inputs) as st:
                st.result = {"v": ctx.inputs["n"]}
            await ctx.progress(1.0)
            return {"done": ctx.inputs["n"]}

        self.reg("w", work)
        a = self.js.submit_job("w", None, {"n": "low"}, 8)
        b = self.js.submit_job("w", None, {"n": "high"}, 1)
        c = self.js.submit_job("w", None, {"n": "after_low"}, 1, depends_on=[a["id"]])
        self.js.light_slots = 1
        await self.js.wait_idle()
        self.assertEqual(self.log, ["high", "low", "after_low"])
        j = self.js.get_job(c["id"])
        self.assertEqual(j["status"], S.COMPLETED)
        self.assertIn('"done": "after_low"', j["output_manifest"])
        self.assertEqual(self.js.stages(c["id"])[0]["status"], S.COMPLETED)

    async def test_idempotency_and_cycle(self):
        async def work(ctx):
            return {}

        self.reg("w", work)
        j1 = self.js.submit_job("w", None, {}, idempotency_key="btn:1")
        j2 = self.js.submit_job("w", None, {}, idempotency_key="btn:1")
        self.assertEqual(j1["id"], j2["id"])
        self.assertFalse(S.JobService._has_cycle(self.hub.db, j1["id"]))

    async def test_retry_recoverable_then_fail(self):
        calls = {"n": 0}

        async def flaky(ctx):
            calls["n"] += 1
            raise Recoverable("network gaya")

        async def broken(ctx):
            raise HubError("ye galat hai")

        self.reg("flaky", flaky, max_attempts=2)
        self.reg("broken", broken)
        f = self.js.submit_job("flaky", None, {})
        b = self.js.submit_job("broken", None, {})
        dep = self.js.submit_job("broken", None, {}, depends_on=[b["id"]])
        await self.js.wait_idle()
        self.assertEqual(self.js.get_job(f["id"])["status"], S.RETRY)  # waiting for backoff
        self.hub.db.execute("UPDATE jobs SET not_before = 0 WHERE id = ?", (f["id"],))
        await self.js.wait_idle()
        jf = self.js.get_job(f["id"])
        self.assertEqual((jf["status"], calls["n"]), (S.FAILED, 2))
        jb = self.js.get_job(b["id"])
        self.assertEqual((jb["status"], jb["error_message"]), (S.FAILED, "ye galat hai"))
        self.assertEqual(self.js.get_job(dep["id"])["error_code"], "dependency_failed")
        self.js.retry_job(b["id"])
        self.assertEqual(self.js.get_job(b["id"])["status"], S.QUEUED)

    async def test_pause_cancel_running_at_stage_boundary(self):
        gate = asyncio.Event()

        async def long(ctx):
            async with ctx.stage("one", {}) as st:
                st.result = {"ok": 1}
                await gate.wait()
            async with ctx.stage("two", {}) as st:
                st.result = {"ok": 2}
            return {"finished": True}

        self.reg("long", long)
        j = self.js.submit_job("long", None, {})
        await self.js.tick()
        await asyncio.sleep(0.05)
        self.assertEqual(self.js.pause_job(j["id"]), "pause_requested")
        gate.set()
        await self.js.wait_idle()
        self.assertEqual(self.js.get_job(j["id"])["status"], S.PAUSED)
        self.assertEqual([s["stage_name"] for s in self.js.stages(j["id"]) if s["status"] == S.COMPLETED], ["one"])
        self.js.resume_job(j["id"])
        await self.js.wait_idle()
        self.assertEqual(self.js.get_job(j["id"])["status"], S.COMPLETED)
        q = self.js.submit_job("long", None, {})
        self.js.pause_job(q["id"])
        self.assertEqual(self.js.cancel_job(q["id"]), "cancelled")
        with self.assertRaises(Conflict):
            self.js.cancel_job(q["id"])

    async def test_waiting_for_approval(self):
        async def gated(ctx):
            async with ctx.stage("draft", {}) as st:
                st.result = {"draft": "ok"}
            if "storyboard" not in ctx.outputs.get("approvals", []):
                ctx.wait_for_approval("storyboard")
            return {"rendered": True}

        self.reg("gated", gated)
        j = self.js.submit_job("gated", None, {})
        await self.js.wait_idle()
        self.assertEqual(self.js.get_job(j["id"])["status"], S.WAIT_APPROVAL)
        self.js.approve_job(j["id"])
        await self.js.wait_idle()
        jj = self.js.get_job(j["id"])
        self.assertEqual(jj["status"], S.COMPLETED)
        self.assertIn("rendered", jj["output_manifest"])

    async def test_heavy_slot_limit(self):
        running = {"now": 0, "max": 0}

        async def heavy(ctx):
            running["now"] += 1
            running["max"] = max(running["max"], running["now"])
            await asyncio.sleep(0.05)
            running["now"] -= 1
            return {}

        self.reg("heavy", heavy, heavy=True)
        for _ in range(3):
            self.js.submit_job("heavy", None, {})
        await self.js.wait_idle()
        self.assertEqual(running["max"], 1)
