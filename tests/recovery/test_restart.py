"""Restart recovery: a job interrupted mid-way (crash / power cut) resumes after restart and skips finished stages."""
from app.container import build_hub
from app.scheduler import service as S
from tests.helpers import TempDirCase, make_settings


class RestartTests(TempDirCase):
    async def test_crash_then_resume_from_checkpoint(self):
        settings = make_settings(self.tmp)
        runs: list[str] = []

        def register(hub, crash: bool):
            async def job(ctx):
                async with ctx.stage("voices", {"t": 1}) as st:
                    if not st.skipped:
                        runs.append("voices")
                        st.result = {"files": 3}
                async with ctx.stage("render", {"t": 1}) as st:
                    if not st.skipped:
                        runs.append("render")
                        if crash:
                            raise SystemExit("power cut")  # simulate the process dying mid-stage
                        st.result = {"mp4": "x"}
                return {"ok": True}

            hub.jobs.register("film", job)

        hub1 = build_hub(settings)
        register(hub1, crash=True)
        j = hub1.jobs.submit_job("film", None, {})
        try:
            await hub1.jobs.tick()
            await hub1.jobs._running[j["id"]]
        except BaseException:
            pass
        # emulate a hard crash: row still says running (no clean shutdown)
        hub1.db.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (j["id"],))
        hub1.db.close()

        hub2 = build_hub(settings)  # "laptop restarted"
        register(hub2, crash=False)
        self.assertEqual(hub2.jobs.reconcile()["resumed"], 1)
        self.assertEqual(hub2.jobs.get_job(j["id"])["status"], S.RETRY)
        await hub2.jobs.wait_idle()
        self.assertEqual(hub2.jobs.get_job(j["id"])["status"], S.COMPLETED)
        self.assertEqual(runs, ["voices", "render", "render"])  # voices NOT redone
        hub2.db.close()

    async def test_job_persists_across_restart(self):
        settings = make_settings(self.tmp)
        hub1 = build_hub(settings)

        async def noop(ctx):
            return {}

        hub1.jobs.register("x", noop)
        j = hub1.jobs.submit_job("x", None, {"a": 1}, 2)
        hub1.db.close()
        hub2 = build_hub(settings)
        row = hub2.jobs.get_job(j["id"])
        self.assertEqual((row["status"], row["priority"], row["input_manifest"]), (S.QUEUED, 2, '{"a": 1}'))
        hub2.db.close()
