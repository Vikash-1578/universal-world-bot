"""Persistent job scheduler (master prompt section 17).

* Every job is written to SQLite *before* submission is acknowledged.
* States: queued, waiting_for_resources, running, waiting_for_approval, paused, retry_pending,
  completed, failed, cancel_requested, cancelled.
* Dependencies (cycle-checked), priorities (1 = highest), heavy/light worker limits.
* Stages with checkpoints: a finished stage is skipped on resume if its input checksum is unchanged.
* Bounded retries with backoff, only for recoverable errors.
* Pause / cancel: queued jobs stop immediately; running jobs stop at the next stage boundary or
  `ctx.check()` call (reported honestly to the owner).
* Start-up reconciliation: jobs left `running` by a crash go back to `retry_pending` and resume from
  their last completed stage.
* Idempotency keys stop double button-presses from creating duplicate jobs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from app.core.errors import Conflict, HubError, InvalidInput, NotFound, Recoverable
from app.core.events import EventBus
from app.observability.log import get_logger, redact
from app.storage.db import Database, dumps, loads

log = get_logger(__name__)

QUEUED, WAIT_RES, RUNNING, WAIT_APPROVAL, PAUSED = "queued", "waiting_for_resources", "running", "waiting_for_approval", "paused"
RETRY, COMPLETED, FAILED, CANCEL_REQ, CANCELLED = "retry_pending", "completed", "failed", "cancel_requested", "cancelled"
STATES = (QUEUED, WAIT_RES, RUNNING, WAIT_APPROVAL, PAUSED, RETRY, COMPLETED, FAILED, CANCEL_REQ, CANCELLED)
ACTIVE = (QUEUED, WAIT_RES, RUNNING, WAIT_APPROVAL, PAUSED, RETRY, CANCEL_REQ)
FINAL = (COMPLETED, FAILED, CANCELLED)
RUNNABLE = (QUEUED, RETRY, WAIT_RES)

LABEL = {QUEUED: "⏳ line me", WAIT_RES: "⏳ resource ka wait", RUNNING: "⚙️ chal raha", WAIT_APPROVAL: "✋ tumhari approval chahiye",
         PAUSED: "⏸ paused", RETRY: "🔁 dobara try hoga", COMPLETED: "✅ ho gaya", FAILED: "❌ fail", CANCEL_REQ: "🛑 ruk raha",
         CANCELLED: "🚫 cancel"}


class Cancelled(Exception):
    pass


class Paused(Exception):
    pass


class NeedsApproval(Exception):
    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


@dataclass
class JobType:
    name: str
    handler: Callable[["JobContext"], Awaitable[dict]]
    heavy: bool = False
    max_attempts: int = 3
    title: str = ""


def checksum(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


class JobContext:
    """What a job handler gets: inputs, a work folder, progress reporting, stages and control checks."""

    def __init__(self, svc: "JobService", job: dict) -> None:
        self.svc = svc
        self.job = job
        self.id: int = job["id"]
        self.inputs: dict = loads(job["input_manifest"], {})
        self.outputs: dict = loads(job["output_manifest"], {}) or {}
        self.workdir: Path = svc.work_root / f"job_{self.id}"
        self.workdir.mkdir(parents=True, exist_ok=True)

    def check(self) -> None:
        """Raise if the owner asked to pause / cancel. Call this between expensive steps."""
        row = self.svc.db.one("SELECT control FROM jobs WHERE id = ?", (self.id,))
        ctl = row["control"] if row else None
        if ctl == "cancel":
            raise Cancelled()
        if ctl == "pause":
            raise Paused()

    async def progress(self, fraction: float, stage: str | None = None) -> None:
        fraction = max(0.0, min(1.0, float(fraction)))
        vals: dict[str, Any] = {"progress": round(fraction, 3), "heartbeat_at": time.time()}
        if stage is not None:
            vals["stage"] = stage[:80]
        self.svc.db.update("jobs", self.id, vals)
        await self.svc.bus.publish("job.progress", job_id=self.id, progress=fraction, stage=stage)

    def stage_done(self, name: str, input_sum: str | None = None) -> dict | None:
        row = self.svc.db.one("SELECT * FROM job_stages WHERE job_id = ? AND stage_name = ?", (self.id, name))
        if row and row["status"] == COMPLETED and (input_sum is None or row["input_checksum"] == input_sum):
            return loads(row["checkpoint_path"], {}) if row["checkpoint_path"] and row["checkpoint_path"].startswith("{") else {"path": row["checkpoint_path"]}
        return None

    @asynccontextmanager
    async def stage(self, name: str, inputs: Any = None) -> AsyncIterator["StageHandle"]:
        """`async with ctx.stage("voices", inputs) as st:` — skipped (st.skipped=True) if already done
        with the same inputs. Put results in `st.result` (a small JSON dict); it becomes the checkpoint."""
        self.check()
        isum = checksum(inputs) if inputs is not None else None
        prev = self.stage_done(name, isum)
        handle = StageHandle(name, prev)
        if prev is not None:
            handle.skipped = True
            yield handle
            return
        now = time.time()
        self.svc.db.execute(
            "INSERT INTO job_stages (job_id, stage_name, status, input_checksum, started_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(job_id, stage_name) DO UPDATE SET status = excluded.status, input_checksum = excluded.input_checksum, "
            "started_at = excluded.started_at, finished_at = NULL, error_details = NULL",
            (self.id, name, RUNNING, isum, now))
        self.svc.db.update("jobs", self.id, {"stage": name, "heartbeat_at": now})
        try:
            yield handle
        except BaseException as e:
            self.svc.db.execute("UPDATE job_stages SET status = ?, error_details = ?, finished_at = ? WHERE job_id = ? AND stage_name = ?",
                                (FAILED, redact(f"{type(e).__name__}: {e}")[:300], time.time(), self.id, name))
            raise
        res = handle.result or {}
        self.svc.db.execute("UPDATE job_stages SET status = ?, checkpoint_path = ?, output_checksum = ?, finished_at = ? "
                            "WHERE job_id = ? AND stage_name = ?",
                            (COMPLETED, dumps(res), checksum(res), time.time(), self.id, name))
        self.check()

    def wait_for_approval(self, what: str) -> None:
        raise NeedsApproval(what)


class StageHandle:
    def __init__(self, name: str, prev: dict | None) -> None:
        self.name = name
        self.skipped = False
        self.result: dict = dict(prev or {})


class JobService:
    def __init__(self, db: Database, bus: EventBus, work_root: Path, *, heavy_slots: int = 1, light_slots: int = 2,
                 poll_seconds: float = 1.0) -> None:
        self.db = db
        self.bus = bus
        self.work_root = work_root
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.types: dict[str, JobType] = {}
        self.heavy_slots = max(1, heavy_slots)
        self.light_slots = max(1, light_slots)
        self.poll_seconds = poll_seconds
        self.worker_id = f"{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._running: dict[int, asyncio.Task] = {}
        self._loop_task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._stopping = False

    # ---------------------------------------------------------------- registry
    def register(self, name: str, handler: Callable[[JobContext], Awaitable[dict]], *, heavy: bool = False,
                 max_attempts: int = 3, title: str = "") -> None:
        self.types[name] = JobType(name, handler, heavy, max_attempts, title or name)

    # ---------------------------------------------------------------- submit / query
    def submit_job(self, job_type: str, project_id: int | None, inputs: dict, priority: int = 5, *,
                   depends_on: list[int] | None = None, idempotency_key: str | None = None, chat_id: int | None = None,
                   title: str = "") -> dict:
        if job_type not in self.types:
            raise InvalidInput(f"Unknown job type: {job_type}")
        jt = self.types[job_type]
        priority = max(1, min(9, int(priority)))
        deps = sorted(set(int(d) for d in depends_on or []))

        def tx(db: Database) -> int:
            if idempotency_key:
                row = db.one("SELECT id FROM jobs WHERE idempotency_key = ?", (idempotency_key,))
                if row:
                    return int(row["id"])
            for d in deps:
                if not db.one("SELECT id FROM jobs WHERE id = ?", (d,)):
                    raise NotFound(f"Dependency job {d} nahi mila.")
            jid = db.insert("jobs", {
                "project_id": project_id, "job_type": job_type, "status": QUEUED, "priority": priority,
                "max_attempts": jt.max_attempts, "input_manifest": dumps(inputs), "output_manifest": "{}",
                "idempotency_key": idempotency_key, "chat_id": chat_id, "heavy": int(jt.heavy),
                "title": (title or jt.title)[:120], "created_at": time.time(),
            })
            for d in deps:
                db.insert("job_dependencies", {"job_id": jid, "depends_on_job_id": d})
            if self._has_cycle(db, jid):
                raise Conflict("Job dependencies me loop ban raha hai.")
            return jid

        jid = self.db.tx(tx)
        self._wake.set()
        return self.get_job(jid)

    @staticmethod
    def _has_cycle(db: Database, start: int) -> bool:
        seen: set[int] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            for r in db.all("SELECT depends_on_job_id AS d FROM job_dependencies WHERE job_id = ?", (cur,)):
                if r["d"] == start:
                    return True
                if r["d"] not in seen:
                    seen.add(r["d"])
                    stack.append(r["d"])
        return False

    def get_job(self, job_id: int) -> dict:
        row = self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not row:
            raise NotFound("Job nahi mila.")
        return row

    def list_jobs(self, *, active_only: bool = False, project_id: int | None = None, offset: int = 0, limit: int = 8) -> list[dict]:
        where, params = [], []
        if active_only:
            where.append(f"status IN ({','.join('?' * len(ACTIVE))})")
            params += ACTIVE
        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        sql = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY CASE WHEN status IN ('running','waiting_for_approval') THEN 0 ELSE 1 END, priority, id DESC LIMIT ? OFFSET ?"
        return self.db.all(sql, (*params, limit, offset))

    def stages(self, job_id: int) -> list[dict]:
        return self.db.all("SELECT stage_name, status, error_details FROM job_stages WHERE job_id = ? ORDER BY id", (job_id,))

    # ---------------------------------------------------------------- controls
    def pause_job(self, job_id: int) -> str:
        j = self.get_job(job_id)
        if j["status"] in (QUEUED, RETRY, WAIT_RES):
            self.db.update("jobs", job_id, {"status": PAUSED})
            return "paused"
        if j["status"] == RUNNING:
            self.db.update("jobs", job_id, {"control": "pause"})
            return "pause_requested"  # stops at the next stage boundary
        raise Conflict(f"Is halat me pause nahi ho sakta ({LABEL.get(j['status'], j['status'])}).")

    def resume_job(self, job_id: int) -> str:
        j = self.get_job(job_id)
        if j["status"] != PAUSED:
            raise Conflict("Job paused nahi hai.")
        self.db.update("jobs", job_id, {"status": QUEUED, "control": None})
        self._wake.set()
        return "queued"

    def cancel_job(self, job_id: int) -> str:
        j = self.get_job(job_id)
        if j["status"] in FINAL:
            raise Conflict("Job pehle hi khatam ho chuka hai.")
        if j["status"] == RUNNING:
            self.db.update("jobs", job_id, {"status": CANCEL_REQ, "control": "cancel"})
            return "cancel_requested"
        self.db.update("jobs", job_id, {"status": CANCELLED, "control": None, "finished_at": time.time()})
        self._fail_dependents(job_id)
        return "cancelled"

    def retry_job(self, job_id: int) -> str:
        j = self.get_job(job_id)
        if j["status"] not in (FAILED, CANCELLED):
            raise Conflict("Sirf fail ya cancel hua job dobara chalta hai.")
        self.db.update("jobs", job_id, {"status": QUEUED, "control": None, "attempt_count": 0, "error_code": None,
                                        "error_message": None, "finished_at": None, "not_before": 0})
        self._wake.set()
        return "queued"

    def change_priority(self, job_id: int, priority: int) -> int:
        self.get_job(job_id)
        p = max(1, min(9, int(priority)))
        self.db.update("jobs", job_id, {"priority": p})
        return p

    def approve_job(self, job_id: int) -> str:
        j = self.get_job(job_id)
        if j["status"] != WAIT_APPROVAL:
            raise Conflict("Is job ko approval ki zarurat nahi hai.")
        out = loads(j["output_manifest"], {}) or {}
        out.setdefault("approvals", []).append(out.pop("pending_approval", "step"))
        self.db.update("jobs", job_id, {"status": QUEUED, "output_manifest": dumps(out)})
        self._wake.set()
        return "queued"

    # ---------------------------------------------------------------- start-up recovery
    def reconcile(self) -> dict[str, int]:
        """Called once at start: fix jobs left in a 'running' state by a crash or power cut."""
        now = time.time()
        moved = self.db.execute(
            f"UPDATE jobs SET status = '{RETRY}', locked_by = NULL, not_before = ?, error_message = 'laptop/bot restart hua, wahi se continue' "
            f"WHERE status = '{RUNNING}'", (now,)).rowcount
        cancelled = self.db.execute(
            f"UPDATE jobs SET status = '{CANCELLED}', control = NULL, finished_at = ? WHERE status = '{CANCEL_REQ}'", (now,)).rowcount
        paused = self.db.execute(
            f"UPDATE jobs SET status = '{PAUSED}', control = NULL WHERE control = 'pause' AND status = '{RETRY}'").rowcount
        self.db.execute(f"UPDATE job_stages SET status = '{FAILED}', error_details = 'interrupted' WHERE status = '{RUNNING}'")
        if moved or cancelled:
            log.info("reconcile: resumed=%s cancelled=%s paused=%s", moved, cancelled, paused)
        return {"resumed": moved, "cancelled": cancelled, "paused": paused}

    # ---------------------------------------------------------------- worker loop
    async def start(self) -> None:
        self._stopping = False
        self.reconcile()
        self._loop_task = asyncio.create_task(self._loop(), name="scheduler")

    async def stop(self, grace: float = 10.0) -> None:
        self._stopping = True
        self._wake.set()
        for jid in list(self._running):
            self.db.update("jobs", jid, {"control": "pause"})  # ask running jobs to stop at a safe point
        if self._running:
            done, pending = await asyncio.wait(list(self._running.values()), timeout=grace)
            for t in pending:
                t.cancel()
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
        # whatever was still running resumes on the next start
        self.db.execute(f"UPDATE jobs SET status = '{RETRY}', locked_by = NULL, control = NULL WHERE status = '{RUNNING}' AND locked_by = ?",
                        (self.worker_id,))

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.tick()
            except Exception as e:  # noqa: BLE001
                log.error("scheduler_tick_failed err=%s", redact(str(e)))
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass

    def _free(self, heavy: bool) -> bool:
        busy = [self.db.one("SELECT heavy FROM jobs WHERE id = ?", (j,)) for j in self._running]
        n_heavy = sum(1 for b in busy if b and b["heavy"])
        n_light = len(busy) - n_heavy
        return n_heavy < self.heavy_slots if heavy else n_light < self.light_slots

    def _deps_state(self, job_id: int) -> str:
        rows = self.db.all("SELECT j.status FROM job_dependencies d JOIN jobs j ON j.id = d.depends_on_job_id WHERE d.job_id = ?", (job_id,))
        if any(r["status"] in (FAILED, CANCELLED) for r in rows):
            return "broken"
        if all(r["status"] == COMPLETED for r in rows):
            return "ready"
        return "waiting"

    def _fail_dependents(self, job_id: int) -> None:
        for r in self.db.all("SELECT job_id FROM job_dependencies WHERE depends_on_job_id = ?", (job_id,)):
            j = self.db.one("SELECT status FROM jobs WHERE id = ?", (r["job_id"],))
            if j and j["status"] not in FINAL and j["status"] != RUNNING:
                self.db.update("jobs", r["job_id"], {"status": FAILED, "error_code": "dependency_failed",
                                                     "error_message": f"Pehle wala job #{job_id} poora nahi hua.", "finished_at": time.time()})
                self._fail_dependents(r["job_id"])

    async def tick(self) -> list[int]:
        """Start whatever can start now. Returns the ids started (used by tests)."""
        started: list[int] = []
        now = time.time()
        rows = self.db.all(f"SELECT * FROM jobs WHERE status IN ({','.join('?' * len(RUNNABLE))}) AND not_before <= ? "
                           "ORDER BY priority, created_at, id", (*RUNNABLE, now))
        for job in rows:
            if job["id"] in self._running:
                continue
            deps = self._deps_state(job["id"])
            if deps == "broken":
                self.db.update("jobs", job["id"], {"status": FAILED, "error_code": "dependency_failed",
                                                   "error_message": "Pehle wala job fail/cancel hua.", "finished_at": now})
                self._fail_dependents(job["id"])
                continue
            if deps == "waiting":
                continue
            if job["job_type"] not in self.types:
                continue  # handler not registered in this version; leave it queued
            if not self._free(bool(job["heavy"])):
                if job["status"] != WAIT_RES:
                    self.db.update("jobs", job["id"], {"status": WAIT_RES})
                continue
            claimed = self.db.execute(
                f"UPDATE jobs SET status = '{RUNNING}', locked_by = ?, started_at = COALESCE(started_at, ?), heartbeat_at = ?, "
                f"attempt_count = attempt_count + 1 WHERE id = ? AND status IN ({','.join('?' * len(RUNNABLE))})",
                (self.worker_id, now, now, job["id"], *RUNNABLE)).rowcount
            if claimed != 1:
                continue
            fresh = self.get_job(job["id"])
            self._running[job["id"]] = asyncio.create_task(self._execute(fresh), name=f"job-{job['id']}")
            started.append(job["id"])
        return started

    async def _execute(self, job: dict) -> None:
        jid = job["id"]
        jt = self.types[job["job_type"]]
        ctx = JobContext(self, job)
        await self.bus.publish("job.status", job_id=jid, status=RUNNING)
        try:
            ctx.check()
            out = await jt.handler(ctx) or {}
            merged = {**ctx.outputs, **out}
            self.db.update("jobs", jid, {"status": COMPLETED, "progress": 1.0, "output_manifest": dumps(merged),
                                         "finished_at": time.time(), "locked_by": None, "control": None,
                                         "error_code": None, "error_message": None})
            await self.bus.publish("job.status", job_id=jid, status=COMPLETED)
        except Cancelled:
            self.db.update("jobs", jid, {"status": CANCELLED, "finished_at": time.time(), "locked_by": None, "control": None})
            self._fail_dependents(jid)
            await self.bus.publish("job.status", job_id=jid, status=CANCELLED)
        except Paused:
            self.db.update("jobs", jid, {"status": PAUSED, "locked_by": None, "control": None,
                                         "attempt_count": max(0, job["attempt_count"] - 1)})
            await self.bus.publish("job.status", job_id=jid, status=PAUSED)
        except NeedsApproval as e:
            out = {**ctx.outputs, "pending_approval": e.what}
            self.db.update("jobs", jid, {"status": WAIT_APPROVAL, "locked_by": None, "output_manifest": dumps(out),
                                         "attempt_count": max(0, job["attempt_count"] - 1)})
            await self.bus.publish("job.status", job_id=jid, status=WAIT_APPROVAL, what=e.what)
        except asyncio.CancelledError:
            self.db.update("jobs", jid, {"status": RETRY, "locked_by": None, "not_before": time.time()})
            raise
        except BaseException as e:  # noqa: BLE001
            await self._failed(job, ctx, e)
        finally:
            self._running.pop(jid, None)
            self._wake.set()

    async def _failed(self, job: dict, ctx: JobContext, e: BaseException) -> None:
        jid = job["id"]
        recoverable = isinstance(e, (Recoverable, asyncio.TimeoutError, ConnectionError)) or getattr(e, "recoverable", False)
        msg = e.user_message if isinstance(e, HubError) else "Andar ki error aayi (logs me detail hai)."
        code = getattr(e, "code", type(e).__name__)
        log.warning("job_failed id=%s type=%s err=%s", jid, job["job_type"], redact(f"{type(e).__name__}: {e}"))
        if not isinstance(e, HubError):
            log.debug(redact("".join(traceback.format_exception(e))))
        attempts = job["attempt_count"]
        if recoverable and attempts < job["max_attempts"]:
            delay = min(300, 5 * 2 ** (attempts - 1))
            self.db.update("jobs", jid, {"status": RETRY, "locked_by": None, "not_before": time.time() + delay,
                                         "error_code": code, "error_message": msg[:300], "output_manifest": dumps(ctx.outputs)})
            await self.bus.publish("job.status", job_id=jid, status=RETRY, delay=delay)
            return
        self.db.update("jobs", jid, {"status": FAILED, "locked_by": None, "finished_at": time.time(), "control": None,
                                     "error_code": code, "error_message": msg[:300], "output_manifest": dumps(ctx.outputs)})
        self._fail_dependents(jid)
        await self.bus.publish("job.status", job_id=jid, status=FAILED)

    async def wait_idle(self, timeout: float = 10.0) -> None:
        """Test helper: run ticks until nothing is running or runnable."""
        end = time.time() + timeout
        while time.time() < end:
            await self.tick()
            if not self._running:
                await asyncio.sleep(0)
                if not self._running and not await asyncio.to_thread(self._has_runnable_now):
                    return
            await asyncio.sleep(0.02)
        raise TimeoutError("scheduler did not become idle")

    def _has_runnable_now(self) -> bool:
        rows = self.db.all(f"SELECT id FROM jobs WHERE status IN ({','.join('?' * len(RUNNABLE))}) AND not_before <= ?",
                           (*RUNNABLE, time.time()))
        return any(self._deps_state(r["id"]) == "ready" and self.get_job(r["id"])["job_type"] in self.types for r in rows)
