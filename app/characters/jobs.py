"""Library jobs: AI description (Ollama / opt-in cloud) and AI image (local ComfyUI)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.scheduler.service import JobContext

if TYPE_CHECKING:
    from app.container import Hub

DESCRIBE_PROMPT = """Write a visual description for a 2D cartoon {kind} that an image generator can draw consistently.
Name: {name}
Notes: {notes}
Style: {style}
Return ONE English paragraph (max 60 words): body shape, colours, clothes/props, face, distinctive details.
The name may be in Hindi: understand it, but write the description in English.
No story, no background description{bg}."""


def register(hub: "Hub") -> None:
    async def describe(ctx: JobContext) -> dict:
        iid = ctx.inputs["item_id"]
        async with ctx.stage("describe", ctx.inputs) as st:
            if not st.skipped:
                it = hub.library.get(iid)
                p = it["profile"]
                prompt = DESCRIBE_PROMPT.format(kind={"character": "character", "environment": "background location",
                                                       "prop": "object"}[it["kind"]], name=it["name"],
                                                notes=(p.get("description") or p.get("look") or "")[:500], style=p.get("style", "kids cartoon"),
                                                bg="" if it["kind"] == "environment" else " (the character will be on a plain background)")
                text = (await hub.llm.chat(prompt, max_tokens=400, temperature=0.6)).strip().strip('"')[:800]
                new = hub.library.update_profile(iid, {"look": text}, note=f"AI description ({hub.llm.last_provider})")
                st.result = {"version": new["version"]}
            return dict(st.result)

    async def ai_image(ctx: JobContext) -> dict:
        iid = ctx.inputs["item_id"]
        it0 = hub.library.get(iid)
        if not (it0["profile"].get("look") or it0["profile"].get("description")):
            # no description yet (e.g. made from a Hindi script name): ask the AI for an English look first, if it is on
            async with ctx.stage("auto_describe", ctx.inputs) as dst:
                if not dst.skipped:
                    dst.result = {"done": False}
                    try:
                        if await hub.llm.available():
                            await describe(ctx)
                            dst.result = {"done": True}
                    except Exception:  # noqa: BLE001  - image can still be made from the name
                        pass
        async with ctx.stage("generate", ctx.inputs) as st:
            if not st.skipped:
                from app.models.imagegen import BACKGROUND_SUFFIX, CHARACTER_SUFFIX

                it = hub.library.get(iid)
                p = it["profile"]
                base = f"{p.get('style', '')}, {p.get('look') or p.get('description') or it['name']}"
                env = it["kind"] == "environment"
                prompt = base + (BACKGROUND_SUFFIX if env else CHARACTER_SUFFIX)
                w, h = (1344, 768) if env else (832, 1216)

                async def tick() -> None:
                    ctx.check()
                    await ctx.progress(min(0.85, ctx.job.get("progress", 0) + 0.05), "AI image bana raha hai")

                data = await hub.imagegen.generate(prompt, width=w, height=h, progress=tick)
                new, qc = hub.library.add_image(iid, "background" if env else "main", data, source=hub.imagegen.last_provider or "ai")
                st.result = {"version": new["version"], "qc_ok": bool(qc and qc.ok)}
                rc = ctx.inputs.get("recast")
                if rc:  # owner asked from the project's Casting screen: move that role to the new picture
                    hub.library.cast(int(rc["project_id"]), rc["role"], iid)
            return dict(st.result)

    from app.characters.bulk import register as reg_bulk

    reg_bulk(hub)
    hub.jobs.register("library_describe", describe, max_attempts=2, title="AI description")
    hub.jobs.register("library_ai_image", ai_image, heavy=True, max_attempts=2, title="AI image")
