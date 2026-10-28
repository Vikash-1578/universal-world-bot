"""Image processing for library assets (local, Pillow only):

* `cutout`   — remove a plain / green-screen background that touches the border (ported from v1 puppet.key_sprite)
* `analyse`  — QC: transparency, size, and auto-rig hints (neck row, two legs) used later by the 2D animator
* `cover`    — fit a background to an exact frame size (center crop)
* `preview`  — small JPEG for Telegram (cut-out shown on a light checker so transparency is visible)

AI separation is not perfect, so every result has a QC report and the owner can upload a corrected PNG.
"""
from __future__ import annotations

import io
from dataclasses import asdict, dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from app.core.errors import InvalidInput

MAX_SIDE = 1600


def open_image(data: bytes) -> Image.Image:
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001
        raise InvalidInput("Ye image khul nahi rahi.") from e
    if im.width * im.height > 40_000_000:
        raise InvalidInput("Image bahut badi hai.")
    im = ImageOps.exif_transpose(im)
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    return im


def has_alpha(im: Image.Image) -> bool:
    if im.mode not in ("RGBA", "LA", "P"):
        return False
    a = im.convert("RGBA").getchannel("A")
    return a.getextrema()[0] < 250


def cutout(im: Image.Image, thresh: int = 70) -> Image.Image | None:
    """Plain-border picture -> RGBA cut-out cropped to the figure. None if the border is not one plain colour."""
    rgb = im.convert("RGB")
    w, h = rgb.size
    work = rgb.copy()
    c0 = rgb.getpixel((0, 0))
    edge = [rgb.getpixel((int((w - 1) * k / 16), y)) for k in range(17) for y in (0, h - 1)]
    edge += [rgb.getpixel((x, int((h - 1) * k / 16))) for k in range(17) for x in (0, w - 1)]
    near = sum(1 for p in edge if sum(abs(a - b) for a, b in zip(p, c0)) < 90)
    if near < len(edge) * 0.85:
        return None
    mark = tuple(255 - v if abs(255 - 2 * v) > 60 else (0 if v > 127 else 255) for v in c0)
    pts = []
    for k in range(9):
        pts += [(int((w - 1) * k / 8), 0), (int((w - 1) * k / 8), h - 1), (0, int((h - 1) * k / 8)), (w - 1, int((h - 1) * k / 8))]
    for p in pts:
        if work.getpixel(p) != mark:
            ImageDraw.floodfill(work, p, mark, thresh=thresh)
    r0, g0, b0 = ImageChops.difference(work, Image.new("RGB", (w, h), mark)).split()
    alpha = ImageChops.lighter(ImageChops.lighter(r0, g0), b0).point(lambda v: 255 if v > 0 else 0)
    transparent = alpha.histogram()[0] / float(w * h)
    if not 0.15 <= transparent <= 0.95:
        return None
    alpha = alpha.filter(ImageFilter.MinFilter(3))
    band = ImageChops.subtract(alpha.filter(ImageFilter.MaxFilter(7)), alpha.filter(ImageFilter.MinFilter(7)))
    r, g, b = rgb.split()
    g2 = Image.composite(ImageChops.darker(g, ImageChops.lighter(r, b)), g, band)  # remove green fringe
    out = Image.merge("RGBA", (r, g2, b, alpha.filter(ImageFilter.GaussianBlur(0.7))))
    box = alpha.getbbox()
    if not box:
        return None
    out = out.crop(box)
    return out if out.width >= 20 and out.height >= 40 else None


def _rows(alpha: Image.Image) -> list[bytes]:
    w, h = alpha.size
    data = alpha.tobytes()
    return [data[y * w:(y + 1) * w] for y in range(h)]


def _runs(row: bytes, min_len: int) -> list[tuple[int, int]]:
    out, start = [], None
    for x, v in enumerate(list(row) + [0]):
        if v > 128 and start is None:
            start = x
        elif v <= 128 and start is not None:
            if x - start >= min_len:
                out.append((start, x))
            start = None
    return out


@dataclass
class QC:
    ok: bool
    width: int
    height: int
    transparent: bool
    coverage: float
    neck_row: int | None
    legs: bool
    problems: list[str]

    def to_dict(self) -> dict:
        return asdict(self)

    def text(self) -> str:
        lines = [f"{'✅' if self.ok else '⚠️'} {self.width}x{self.height} · transparent: {'haan' if self.transparent else 'nahi'}",
                 f"Rig: gardan {'mili' if self.neck_row is not None else 'nahi mili'} · do pair {'mile' if self.legs else 'nahi mile (dress/janwar ho sakta hai)'}"]
        lines += [f"• {p}" for p in self.problems]
        return "\n".join(lines)


def analyse(im: Image.Image, kind: str = "character") -> QC:
    rgba = im.convert("RGBA")
    w, h = rgba.size
    a = rgba.getchannel("A")
    transparent = a.getextrema()[0] < 250
    coverage = round(1 - a.histogram()[0] / float(w * h), 3)
    problems: list[str] = []
    neck, legs = None, False
    if kind == "character":
        if not transparent:
            problems.append("Background nahi hata — plain/green background wali photo ya transparent PNG bhejo.")
        if min(w, h) < 200:
            problems.append("Image chhoti hai (kam se kam 200px) — animation dhundhli lagegi.")
        if transparent and not 0.08 <= coverage <= 0.95:
            problems.append("Figure bahut chhota ya bahut bada hai frame me.")
        if transparent:
            rows = _rows(a)
            best = None
            for y in range(int(h * 0.12), int(h * 0.45)):
                r = _runs(rows[y], 2)
                if r:
                    width = max(b - x for x, b in r)
                    if best is None or width < best:
                        best, neck = width, y
            min_len = max(2, int(w * 0.04))
            two = [y for y in range(int(h * 0.75), int(h * 0.97)) if len(_runs(rows[y], min_len)) >= 2]
            legs = len(two) >= max(3, int(h * 0.04))
    else:
        if w < 1280 or h < 720:
            problems.append("Background 1280x720 se chhota hai — 1080p video me dhundhla lagega.")
    return QC(not problems, w, h, transparent, coverage, neck, legs, problems)


def cover(im: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(im.convert("RGB"), (w, h), Image.LANCZOS)


def preview(im: Image.Image, max_side: int = 640) -> bytes:
    sp = im.copy()
    sp.thumbnail((max_side, max_side))
    if sp.mode == "RGBA":
        bg = Image.new("RGB", (sp.width + 40, sp.height + 40), (236, 241, 247))
        d = ImageDraw.Draw(bg)
        for y in range(0, bg.height, 20):
            for x in range(0, bg.width, 20):
                if (x // 20 + y // 20) % 2:
                    d.rectangle((x, y, x + 19, y + 19), fill=(222, 228, 236))
        bg.paste(sp, (20, 20), sp)
        sp = bg
    buf = io.BytesIO()
    sp.convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue()


def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
