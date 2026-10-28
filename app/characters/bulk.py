"""Bulk AI pictures for the ready-made templates (owner asked: 'pre-built characters ko AI se banwa do').

One job, one checkpointed stage per template, so pause / restart / a second run continue where it stopped.
* A template that already has a library item with a picture is skipped (never made twice).
* Cloudflare daily limit / bad key -> the job stops cleanly and says so; press again tomorrow to continue.
* A single bad picture does not stop the run; 5 failures in a row do.
Pictures are not auto-approved: QC stays for the owner.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.characters import templates
from app.core.errors import ProviderUnavailable
from app.scheduler.service import JobContext

if TYPE_CHECKING:
    from app.container import Hub

JOB = "library_bulk_ai"
SETS = {"featured": "48 khaas characters + 97 jagah", "all": "saare templates"}


def template_ids(which: str = "featured") -> list[str]:
    if which == "all":
        return [t["id"] for t in templates.entries()]
    base = json.loads(Path(templates.DATA).read_text(encoding="utf-8"))
    hand = [c["id"] for c in base["characters"]]
    return hand + [t["id"] for t in templates.entries(kind="place")]


def has_picture(it: dict) -> bool:
    return ("background" if it["kind"] == "environment" else "main") in it["files"]


def progress(hub: "Hub", which: str = "featured") -> tuple[int, int]:
    """(templates that already have a picture, total)."""
    ids = template_ids(which)
    done = 0
    for tid in ids:
        it = hub.library.find_by_template(tid)
        if it and has_picture(it):
            done += 1
    return done, len(ids)


def register(hub: "Hub") -> None:
    from app.models.imagegen import BACKGROUND_SUFFIX, CHARACTER_SUFFIX

    async def run(ctx: JobContext) -> dict:
        which = ctx.inputs.get("set", "featured")
        ids = template_ids(which)
        made = skipped = failed = streak = 0
        stopped = ""
        for i, tid in enumerate(ids):
            async with ctx.stage(f"t:{tid}"[:60], {"tid": tid}) as st:
                if st.skipped:
                    continue
                it = hub.library.find_by_template(tid)
                if it and has_picture(it):
                    skipped += 1
                    st.result = {"skip": True}
                    continue
                t = templates.get(tid) or {}
                await ctx.progress(i / len(ids), f"{i + 1}/{len(ids)} {t.get('name', tid)[:24]}")
                if it is None:
                    it = hub.library.from_template(tid)
                env = it["kind"] == "environment"
                p = it["profile"]
                prompt = f"{p.get('style', '')}, {p.get('look') or p.get('description') or it['name']}" + (BACKGROUND_SUFFIX if env else CHARACTER_SUFFIX)
                w, h = (1344, 768) if env else (832, 1216)
                try:
                    data = await hub.imagegen.generate(prompt, width=w, height=h)
                    new, qc = hub.library.add_image(it["id"], "background" if env else "main", data,
                                                    source=getattr(hub.imagegen, "last_provider", None) or "ai")
                except ProviderUnavailable as e:
                    if "limit" in e.user_message.lower() or "key" in e.user_message.lower():
                        stopped = e.user_message
                        st.result = {"error": "stopped"}
                        break
                    failed += 1
                    streak += 1
                    st.result = {"error": e.user_message[:80]}
                except Exception as e:  # noqa: BLE001  - one bad picture must not stop the whole run
                    failed += 1
                    streak += 1
                    st.result = {"error": type(e).__name__}
                else:
                    made += 1
                    streak = 0
                    st.result = {"item": it["id"], "version": new["version"], "qc_ok": bool(qc and qc.ok)}
                if streak >= 5:
                    stopped = "Lagatar 5 image fail hui — ruk gaya. Diagnostics / Settings dekho."
                    break
        done, total = progress(hub, which)
        return {"made": made, "skipped": skipped, "failed": failed, "stopped": stopped, "done": done, "total": total}

    hub.jobs.register(JOB, run, heavy=True, max_attempts=1, title="Templates ki AI images")
