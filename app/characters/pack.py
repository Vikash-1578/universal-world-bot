"""Character Pack: ready-made face expressions for one character, made from its OWN main picture.

Only the face is repainted (local ComfyUI, masked img2img); hair, clothes, body and outline are copied back
pixel-for-pixel from the original, so every expression is the same character. The 2D renderer then uses them
automatically: script emotions -> expr:happy / sad / angry / ..., speaking -> expr:talk (mouth), blinking -> expr:blink.

Limitation: the face is repainted by the image AI, so details inside the face (eye shape, moustache) can vary a little
between expressions. Hand / arm poses are NOT made here (that needs a pose-control model).
"""
from __future__ import annotations

import io
from typing import TYPE_CHECKING

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from app.animation.two_d.rig import find_neck
from app.core.errors import Conflict
from app.scheduler.service import JobContext

if TYPE_CHECKING:
    from app.container import Hub

JOB = "library_pack"
EXPR = {
    "happy": ("khush", "big happy smile, cheerful joyful eyes"),
    "sad": ("dukhi", "sad face, downturned mouth, droopy sad eyes"),
    "angry": ("gussa", "angry face, furrowed eyebrows, frowning mouth"),
    "surprised": ("hairan", "surprised face, wide open eyes, small round open mouth, raised eyebrows"),
    "scared": ("dara hua", "scared face, worried raised eyebrows, wide eyes, trembling open mouth"),
    "talk": ("bolta hua", "mouth open as if talking, same calm expression"),
    "blink": ("palak", "both eyes fully closed, relaxed calm face"),
}
ORDER = ("talk", "blink", "happy", "sad", "angry", "surprised", "scared")
PACK_NEGATIVE = ("different character, different face, realistic photo, text, watermark, blurry, deformed, extra eyes, "
                 "cropped, frame, background objects")


def face_box(cut: Image.Image) -> tuple[int, int, int, int]:
    """Face area of a front-facing full-body picture: the head (above the neck), without the top of the hair."""
    a = cut.getchannel("A")
    neck = find_neck(a)
    head = a.crop((0, 0, cut.width, max(2, neck)))
    bb = head.point(lambda v: 255 if v > 128 else 0).getbbox() or (0, 0, cut.width, neck)
    x0, y0, x1, y1 = bb
    hw, hh = x1 - x0, y1 - y0
    return (int(x0 + hw * 0.14), int(y0 + hh * 0.32), int(x1 - hw * 0.14), int(y1 - hh * 0.02))


def scale_for_model(w: int, h: int, long_side: int = 1216) -> tuple[int, int]:
    s = long_side / max(w, h)
    return max(64, int(round(w * s / 8)) * 8), max(64, int(round(h * s / 8)) * 8)


def make_input(cut: Image.Image) -> tuple[bytes, Image.Image, tuple[int, int]]:
    """PNG for ComfyUI: the character on white, with the face area transparent (= the part to repaint).
    Returns (png, soft mask at original size, model size)."""
    cut = cut.convert("RGBA")
    box = face_box(cut)
    mask = Image.new("L", cut.size, 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    size = scale_for_model(*cut.size)
    flat = Image.new("RGB", cut.size, (255, 255, 255))
    flat.paste(cut, (0, 0), cut)
    # resize colour and mask separately: resizing RGBA would blacken the colours under the hole, and the AI
    # must start from the original face (that is what keeps the character recognisable)
    big = flat.resize(size, Image.LANCZOS).convert("RGBA")
    big.putalpha(ImageChops.invert(mask).resize(size, Image.LANCZOS).point(lambda v: 0 if v < 128 else 255))
    buf = io.BytesIO()
    big.save(buf, "PNG")
    soft = mask.filter(ImageFilter.GaussianBlur(max(2, (box[2] - box[0]) // 18)))
    return buf.getvalue(), soft, size


def compose(cut: Image.Image, generated: bytes, soft_mask: Image.Image) -> Image.Image:
    """New face from the AI, everything else (and the transparency) from the original picture."""
    cut = cut.convert("RGBA")
    gen = Image.open(io.BytesIO(generated)).convert("RGB").resize(cut.size, Image.LANCZOS)
    inside = ImageChops.multiply(soft_mask, cut.getchannel("A"))  # never paint outside the character
    rgb = Image.composite(gen, cut.convert("RGB"), inside)
    out = rgb.convert("RGBA")
    out.putalpha(cut.getchannel("A"))
    return out


def register(hub: "Hub") -> None:
    async def run(ctx: JobContext) -> dict:
        iid = ctx.inputs["item_id"]
        exprs = [e for e in ctx.inputs.get("exprs", ORDER) if e in EXPR]
        comfy = hub.imagegen.comfy if hasattr(hub.imagegen, "comfy") else hub.imagegen
        if not hasattr(comfy, "inpaint"):
            raise Conflict("Expression pack ke liye laptop par ComfyUI chalu chahiye (cloud se ye nahi banta).")
        it = hub.library.get(iid)
        main = hub.library.file_path(it, "main")
        if not main:
            raise Conflict("Pehle is character ki main image banao, phir expressions.")
        cut = Image.open(main).convert("RGBA")
        png, soft, _size = make_input(cut)
        look = (it["profile"].get("look") or it["profile"].get("description") or it["name"])[:300]
        style = it["profile"].get("style", "2D cartoon")
        made = []
        for i, e in enumerate(exprs):
            async with ctx.stage(f"expr_{e}", {"item": iid, "main": it["files"]["main"]["sha256"], "e": e}) as st:
                if st.skipped:
                    made.append(e)
                    continue
                await ctx.progress(i / len(exprs), f"{EXPR[e][0]} ({i + 1}/{len(exprs)})")
                prompt = f"{EXPR[e][1]}, same cartoon character face, {style}, {look}"
                data = await comfy.inpaint(png, prompt, negative=PACK_NEGATIVE, denoise=0.72 if e != "talk" else 0.6)
                face = compose(cut, data, soft)
                buf = io.BytesIO()
                face.save(buf, "PNG")
                new, _qc = hub.library.add_image(iid, f"expr:{e}", buf.getvalue(), source="pack")
                st.result = {"version": new["version"]}
                made.append(e)
        rc = ctx.inputs.get("recast")
        if rc:
            hub.library.cast(int(rc["project_id"]), rc["role"], iid)
        return {"item": iid, "made": made}

    hub.jobs.register(JOB, run, heavy=True, max_attempts=2, title="Expression pack")
