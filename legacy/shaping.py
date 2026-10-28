"""Correct Hindi (Devanagari) text drawing even when Pillow has no Raqm.

Pillow needs the Raqm library (plus FriBiDi) to join Devanagari letters: matras such as "ि" before the letter,
half letters (स्क), conjuncts. Linux Pillow wheels have it; on Windows FriBiDi is usually missing, and then
"दिन" is drawn as "दनि". In that case we shape the text with HarfBuzz (uharfbuzz wheel) and draw the glyph
outlines from the font ourselves (fontTools), so the result is the same on every computer.
"""
from __future__ import annotations

import os
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, features

SS = 4  # supersampling for smooth glyph edges


@lru_cache(maxsize=1)
def native_ok() -> bool:
    if os.environ.get("UW_FORCE_HB") == "1":
        return False
    try:
        return bool(features.check("raqm"))
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def hb_ok() -> bool:
    try:
        import fontTools.ttLib  # noqa: F401
        import uharfbuzz  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _pen_class():
    from fontTools.pens.basePen import BasePen

    class _Pen(BasePen):
        """fontTools pen -> list of polygons (curves flattened, composite glyphs decomposed)."""

        def __init__(self, glyphset, scale: float, asc: float) -> None:
            super().__init__(glyphset)
            self.s, self.asc = scale, asc
            self.polys: list[list[tuple[float, float]]] = []
            self.cur: list[tuple[float, float]] = []

        def _pt(self, p):
            return (p[0] * self.s * SS, (self.asc - p[1]) * self.s * SS)

        def _moveTo(self, p):  # noqa: N802
            self._flush()
            self.cur = [self._pt(p)]

        def _lineTo(self, p):  # noqa: N802
            self.cur.append(self._pt(p))

        def _qCurveToOne(self, c, p):  # noqa: N802
            p0 = self._getCurrentPoint()
            for k in range(1, 7):
                t = k / 6
                self.cur.append(self._pt(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p[0],
                                          (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p[1])))

        def _curveToOne(self, c1, c2, p3):  # noqa: N802
            p0 = self._getCurrentPoint()
            for k in range(1, 9):
                t = k / 8
                self.cur.append(self._pt((
                    (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * c1[0] + 3 * (1 - t) * t * t * c2[0] + t ** 3 * p3[0],
                    (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * c1[1] + 3 * (1 - t) * t * t * c2[1] + t ** 3 * p3[1])))

        def _closePath(self):  # noqa: N802
            self._flush()

        def _endPath(self):  # noqa: N802
            self._flush()

        def _flush(self):
            if len(self.cur) >= 3:
                self.polys.append(self.cur)
            self.cur = []

    return _Pen


class ShapedFont:
    def __init__(self, path: str, size: int, ascent: int) -> None:
        import uharfbuzz as hb
        from fontTools.ttLib import TTFont

        with open(path, "rb") as fh:
            data = fh.read()
        self.face = hb.Face(data)
        self.hbfont = hb.Font(self.face)
        self.upem = self.face.upem
        self.scale = size / self.upem
        self.size = size
        self.ascent = ascent  # pixels from top of the text box to the baseline (Pillow's value)
        import io as _io

        self.tt = TTFont(_io.BytesIO(data))
        self.glyphs = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        self.cache: dict[int, tuple[Image.Image, int, int] | None] = {}

    def shape(self, text: str):
        import uharfbuzz as hb

        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hbfont, buf, {})
        return list(zip(buf.glyph_infos, buf.glyph_positions))

    def width(self, text: str) -> float:
        return sum(p.x_advance for _, p in self.shape(text)) * self.scale

    def _glyph(self, gid: int):
        if gid in self.cache:
            return self.cache[gid]
        name = self.order[gid] if gid < len(self.order) else None
        res = None
        if name is not None:
            pen = _pen_class()(self.glyphs, self.scale, self.ascent / self.scale)
            try:
                self.glyphs[name].draw(pen)
            except Exception:  # noqa: BLE001
                pen.polys = []
            pen._flush()
            if pen.polys:
                xs = [x for poly in pen.polys for x, _ in poly]
                ys = [y for poly in pen.polys for _, y in poly]
                x0, y0 = int(min(xs)) - 2, int(min(ys)) - 2
                w, h = int(max(xs)) - x0 + 3, int(max(ys)) - y0 + 3
                mask = Image.new("1", (max(1, w), max(1, h)), 0)
                for poly in pen.polys:  # even-odd fill: XOR every contour
                    m = Image.new("1", mask.size, 0)
                    ImageDraw.Draw(m).polygon([(x - x0, y - y0) for x, y in poly], fill=1)
                    mask = ImageChops.logical_xor(mask, m)
                small = mask.convert("L").resize((max(1, w // SS), max(1, h // SS)), Image.BOX)
                res = (small, x0 // SS, y0 // SS)
        self.cache[gid] = res
        return res

    def mask(self, text: str) -> tuple[Image.Image, float]:
        """Text as an L mask whose top-left is the text box origin (like Pillow's draw.text), and its advance."""
        shaped = self.shape(text)
        adv = sum(p.x_advance for _, p in shaped) * self.scale
        w = int(adv + self.size) + 4
        h = int(self.size * 1.6) + 4
        out = Image.new("L", (w, h), 0)
        pen_x = 0.0
        for info, pos in shaped:
            g = self._glyph(info.codepoint)
            if g is not None:
                img, gx, gy = g
                x = int(round(pen_x + pos.x_offset * self.scale)) + gx
                y = gy - int(round(pos.y_offset * self.scale))
                out.paste(ImageChops.lighter(out.crop((x, y, x + img.width, y + img.height)), img), (x, y))
            pen_x += pos.x_advance * self.scale
        return out, adv


@lru_cache(maxsize=32)
def shaped_font(path: str, size: int, ascent: int) -> ShapedFont:
    return ShapedFont(path, size, ascent)


def font_path(font) -> str | None:
    return getattr(font, "path", None)


def needs_shaping(text: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in text) and not native_ok() and hb_ok()


def width(font, text: str) -> float:
    if needs_shaping(text) and font_path(font):
        return shaped_font(font_path(font), font.size, font.getmetrics()[0]).width(text)
    return font.getlength(text)


def draw(draw_: ImageDraw.ImageDraw, xy, text: str, font, fill, stroke_width: int = 0, stroke_fill=None) -> float:
    """Draw like ImageDraw.text; returns the advance width."""
    path = font_path(font)
    if not (needs_shaping(text) and path):
        draw_.text(xy, text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        return font.getlength(text)
    sf = shaped_font(path, font.size, font.getmetrics()[0])
    mask, adv = sf.mask(text)
    img = draw_._image
    x, y = int(round(xy[0])), int(round(xy[1]))
    if stroke_width and stroke_fill is not None:
        pad = stroke_width
        big = Image.new("L", (mask.width + 2 * pad, mask.height + 2 * pad), 0)
        big.paste(mask, (pad, pad))
        st = big.filter(ImageFilter.MaxFilter(2 * stroke_width + 1))
        img.paste(Image.new(img.mode, st.size, stroke_fill), (x - pad, y - pad), st)
    img.paste(Image.new(img.mode, mask.size, fill), (x, y), mask)
    return adv
