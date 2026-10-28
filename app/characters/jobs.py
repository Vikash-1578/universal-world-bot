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
{context}
The name may be in Hindi or Hinglish. First translate it in your head (e.g. लोमड़ी = fox, बिल्ली = cat, चिड़िया = small bird,
खरगोश = rabbit, कछुआ = tortoise, शेर = lion, बागान/बगीचा = garden, जंगल = jungle). Draw exactly THAT: an animal name means
that animal (cute cartoon animal, may stand on two legs) - never a human child instead.
Return ONE English paragraph (max 60 words) that starts with what it is (e.g. "A cute orange cartoon fox ..."):
body shape, colours, clothes/props, face, distinctive details.
No story, no background description{bg}."""


def is_english(text: str) -> bool:
    letters = [c for c in text or "" if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if c.isascii()) / len(letters) > 0.8


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
                                                bg="" if it["kind"] == "environment" else " (the character will be on a plain background)",
                                                context=(f"What the story says about it (use this to know WHAT it is, e.g. which animal): {p['story']}"
                                                         if p.get("story") else ""))
                text = (await hub.llm.chat(prompt, max_tokens=400, temperature=0.6)).strip().strip('"')[:800]
                new = hub.library.update_profile(iid, {"look": text}, note=f"AI description ({hub.llm.last_provider})")
                st.result = {"version": new["version"]}
            return dict(st.result)

    async def ai_image(ctx: JobContext) -> dict:
        iid = ctx.inputs["item_id"]
        it0 = hub.library.get(iid)
        if ctx.inputs.get("redescribe") or not is_english(it0["profile"].get("look") or it0["profile"].get("description") or ""):
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

    from app.characters.pack import register as reg_pack

    reg_pack(hub)
    hub.jobs.register("library_describe", describe, max_attempts=2, title="AI description")
    hub.jobs.register("library_ai_image", ai_image, heavy=True, max_attempts=2, title="AI image")
