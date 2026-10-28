"""2D animation render job (Milestone 6): plan -> one checkpointed stage per scene -> join -> validate -> export.

A restart resumes at the first unfinished scene (finished scene files are checked by sha256 before reuse).
Final quality needs an approved storyboard (approval gate); preview works on a draft too.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.errors import Conflict, HubError
from app.scheduler.service import JobContext, checksum
from app.storage.db import dumps, loads
from app.storage.files import sha256

if TYPE_CHECKING:
    from app.container import Hub

JOB = "anim_2d"


def start(hub: "Hub", project_id: int, quality: str, chat_id: int | None = None, key: str | None = None) -> dict:
    from app.animation.two_d import planner

    ptype = hub.projects.get_project(project_id)["project_type"]
    if ptype != "2d":
        raise Conflict("Ye project 2D nahi hai. 3D (Blender) pipeline Milestone 7 me banegi; 2D renderer isse nahi chalega.")
    if quality == "final" and hub.storyboards.state(project_id).get("status") != "approved":
        raise Conflict("Final video ke liye pehle Storyboard approve karo. (Preview abhi bhi bana sakte ho.)")
    require_pictures(planner.build(hub, project_id, quality))  # fail fast with a clear message
    title = "2D preview video" if quality == "preview" else "2D final video"
    return hub.jobs.submit_job(JOB, project_id, {"project_id": project_id, "quality": quality}, 4 if quality == "preview" else 5,
                               idempotency_key=key, chat_id=chat_id, title=title)


def require_pictures(plan: dict) -> None:
    """No stand-in 'putla' / plain sky in a real video: every role and place needs its picture first."""
    if plan.get("warnings"):
        names = [w.split("'")[1] if "'" in w else w for w in plan["warnings"]]
        raise Conflict("Video nahi banegi — inki image nahi hai: " + ", ".join(names[:8]) +
                       ". 🎭 Casting / 🧍 Characters me AI image banao ya apni image do.")


def exports(hub: "Hub", project_id: int, limit: int = 8) -> list[dict]:
    rows = hub.db.all("SELECT * FROM assets WHERE project_id = ? AND asset_type = 'export:video' ORDER BY id DESC LIMIT ?",
                      (int(project_id), limit))
    for r in rows:
        r["meta"] = loads(r.pop("metadata_json"), {})
        r["abs"] = hub.settings.data_dir / r["relative_path"]
    return rows


def _ffmpeg(hub: "Hub") -> str:
    from app.observability.diagnostics import find_ffmpeg

    exe = find_ffmpeg(hub.settings)
    if not exe:
        raise HubError("FFmpeg nahi mila — video nahi ban sakti. Diagnostics dekho.")
    return exe


async def _join(ffmpeg: str, parts: list[Path], out: Path) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    proc = await asyncio.create_subprocess_exec(ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                                                "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out),
                                                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await asyncio.wait_for(proc.communicate(), timeout=600)
    if proc.returncode != 0 or not out.exists():
        raise HubError("Scenes jodte waqt FFmpeg fail hua.", detail=err.decode(errors="replace")[-300:])


def register(hub: "Hub") -> None:
    from app.animation.two_d import planner, puppet

    async def render(ctx: JobContext) -> dict:
        pid, quality = int(ctx.inputs["project_id"]), ctx.inputs.get("quality", "preview")
        ffmpeg = _ffmpeg(hub)
        async with ctx.stage("plan", ctx.inputs) as st:
            if not st.skipped:
                if quality == "final" and hub.storyboards.state(pid).get("status") != "approved":
                    raise Conflict("Storyboard approved nahi hai — final video ruki.")
                plan = planner.build(hub, pid, quality)
                require_pictures(plan)
                (ctx.workdir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
                st.result = {"sum": checksum(plan), "scenes": len(plan["scenes"]), "seconds": plan["seconds"],
                             "warnings": plan["warnings"]}
            info = dict(st.result)
        plan = json.loads((ctx.workdir / "plan.json").read_text(encoding="utf-8"))
        w, h, fps = plan["width"], plan["height"], plan["fps"]
        parts: list[Path] = []
        total = len(plan["scenes"])
        loop = asyncio.get_running_loop()
        for i, sc in enumerate(plan["scenes"]):
            async with ctx.stage(f"scene_{sc['n']}", {"plan": info["sum"], "scene": sc}) as st:
                out = ctx.workdir / f"scene_{sc['n']:03d}.mp4"
                if st.skipped and out.exists() and sha256(out) == st.result.get("sha256"):
                    parts.append(out)
                    continue
                await ctx.progress(0.05 + 0.8 * i / total, f"scene {sc['n']}/{total}")
                last = [0.0]

                def on_frame(frac: float, i: int = i) -> None:  # runs in the render thread
                    now = time.monotonic()
                    if now - last[0] > 3:
                        last[0] = now
                        asyncio.run_coroutine_threadsafe(ctx.progress(0.05 + 0.8 * (i + frac) / total, f"scene {i + 1}/{total}"), loop)

                def work() -> None:
                    scene = planner.load_scene(hub, sc, fps)
                    puppet.render_puppet(scene, w, h, fps, out, ffmpeg, crf=plan["crf"], on_frame=on_frame)

                await asyncio.to_thread(work)
                st.result = {"path": out.name, "sha256": sha256(out)}
                parts.append(out)
        async with ctx.stage("join", {"plan": info["sum"], "parts": [p.name for p in parts]}) as st:
            joined = ctx.workdir / "joined.mp4"
            if not st.skipped or not joined.exists():
                await ctx.progress(0.88, "join")
                await _join(ffmpeg, parts, joined)
                st.result = {"sha256": sha256(joined)}
        async with ctx.stage("validate", {"sha": st.result.get("sha256")}) as vst:
            from app.exports.validate import check, probe

            probe_info = await probe(hub.settings, joined)
            problems = check(probe_info, width=w, height=h, fps=fps, min_seconds=1.0, need_audio=True)
            if problems:
                raise HubError("Bani video sahi nahi hai: " + "; ".join(problems))
            vst.result = {"duration": probe_info["duration"], "video": probe_info["video"]}
        async with ctx.stage("export", {"sha": st.result.get("sha256")}) as est:
            if not est.skipped:
                p = hub.projects.get_project(pid)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                folder = hub.projects.folder(pid, "exports")
                final = folder / f"{p['id']}_{quality}_{w}x{h}_{stamp}_job{ctx.id}.mp4"
                n = 2
                while final.exists() or hub.db.one("SELECT id FROM assets WHERE relative_path = ?",
                                                     (str(final.relative_to(hub.settings.data_dir)).replace("\\", "/"),)):
                    final = folder / f"{p['id']}_{quality}_{w}x{h}_{stamp}_job{ctx.id}_{n}.mp4"
                    n += 1
                final.write_bytes(joined.read_bytes())
                rel = str(final.relative_to(hub.settings.data_dir)).replace("\\", "/")
                meta = {"quality": quality, "width": w, "height": h, "fps": fps, "seconds": round(vst.result["duration"], 2),
                        "scenes": total, "job_id": ctx.id, "silent_audio": True, "warnings": info.get("warnings", [])}
                aid = hub.db.insert("assets", {"asset_type": "export:video", "relative_path": rel, "checksum": sha256(final),
                                               "metadata_json": dumps(meta), "protected": 1 if quality == "final" else 0,
                                               "project_id": pid, "created_at": time.time()})
                hub.db.insert("exports", {"project_id": pid, "preset": f"2d_{quality}", "output_path": rel,
                                          "resolution": f"{w}x{h}", "frame_rate": fps, "duration_seconds": meta["seconds"],
                                          "checksum": sha256(final), "validation_json": dumps({"problems": [], "probe": vst.result}),
                                          "approval_status": "pending", "kind": quality, "created_at": time.time()})
                hub.projects.write_manifest(pid)  # the project manifest now lists this video
                hub.audit.record("export_video", "ok", "project", pid, asset=aid, quality=quality)
                est.result = {"asset_id": aid, "path": rel, "bytes": final.stat().st_size, **meta}
            return dict(est.result)

    hub.jobs.register(JOB, render, heavy=True, max_attempts=2, title="2D animation video")
