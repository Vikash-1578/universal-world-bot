"""Local image tools (Pillow): title text on thumbnails/posters, caption images, upscale.

Image models draw text badly, so for thumbnails, posters and video captions the
picture is made WITHOUT text and the words are written here with real fonts.
Fonts for Latin and Devanagari are bundled in app/assets/fonts (Noto, OFL), and
mixed Hindi + English text is drawn run by run with the right font.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.services import shaping

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
_LATIN_FONTS = (
    str(FONT_DIR / "NotoSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "arialbd.ttf",
    "Arial Bold.ttf",
)
_DEVA_FONTS = (
    str(FONT_DIR / "NotoSansDevanagari-Bold.ttf"),
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
    "Nirmala.ttf",
    "mangal.ttf",
)
MAX_SIDE = 4096


def is_deva(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


@lru_cache(maxsize=64)
def _font(script: str, size: int):
    for n in (_DEVA_FONTS if script == "deva" else _LATIN_FONTS):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1, scalable
    except TypeError:
        return ImageFont.load_default()


def runs(text: str) -> list[tuple[str, str]]:
    """Split into (script, chunk). Spaces, digits and punctuation stay with the run before them."""
    out: list[tuple[str, str]] = []
    cur = "latin"
    for ch in text:
        if is_deva(ch):
            cur = "deva"
        elif ch.isalpha():
            cur = "latin"
        if out and out[-1][0] == cur:
            out[-1] = (cur, out[-1][1] + ch)
        else:
            out.append((cur, ch))
    return out


def text_width(text: str, size: int) -> float:
    return sum(shaping.width(_font(s, size), t) for s, t in runs(text))


def draw_text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, size: int, fill, stroke_width: int = 0, stroke_fill=None) -> None:
    x, y = xy
    for script, chunk in runs(text):
        f = _font(script, size)
        x += shaping.draw(draw, (x, y), chunk, f, fill, stroke_width, stroke_fill)


def wrap(text: str, size: int, max_w: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if text_width(trial, size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit(text: str, max_w: int, max_h: int, start: int, min_size: int = 18, max_lines: int = 4) -> tuple[int, list[str], int]:
    """Biggest font size whose wrapped lines fit the box. Returns (size, lines, line_height)."""
    size = start
    while size >= min_size:
        lines = wrap(text, size, max_w)
        line_h = int(size * 1.25)
        if len(lines) <= max_lines and line_h * len(lines) <= max_h and all(text_width(ln, size) <= max_w for ln in lines):
            return size, lines, line_h
        size -= 3
    return min_size, wrap(text, min_size, max_w)[:max_lines], int(min_size * 1.25)


def _to_jpeg(img: Image.Image, quality: int = 92) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Resize + centre-crop so the picture fills w x h."""
    return ImageOps.fit(img.convert("RGB"), (w, h), Image.LANCZOS, centering=(0.5, 0.5))


def overlay_title(data: bytes, title: str, subtitle: str | None = None, layout: str = "thumb") -> bytes:
    """Write `title` (and optional `subtitle`) on the picture. layout: thumb | poster."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    w, h = img.size
    title = (title or "").strip()
    if not any(is_deva(c) for c in title):
        title = title.upper()
    subtitle = (subtitle or "").strip()
    if not title:
        return _to_jpeg(img)

    # darken the text zone so letters stay readable on any picture
    shade = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    zone_top = int(h * (0.62 if layout == "poster" else 0.50))
    steps = max(1, h - zone_top)
    for i in range(steps):
        alpha = int(185 * (i / steps) ** 0.9)
        sd.line([(0, zone_top + i), (w, zone_top + i)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")
    draw = ImageDraw.Draw(img)

    margin = int(w * 0.06)
    max_w = w - 2 * margin
    title_area_h = int(h * (0.34 if layout == "thumb" else 0.22))
    start = int(h * (0.16 if layout == "thumb" else 0.085))
    size, lines, line_h = fit(title, max_w, title_area_h, start)
    sub_size = 0
    sub_lines: list[str] = []
    sub_lh = 0
    sub_h = 0
    if subtitle:
        sub_size, sub_lines, sub_lh = fit(subtitle, max_w, int(h * 0.12), int(h * 0.05), 16, 2)
        sub_h = sub_lh * len(sub_lines) + int(h * 0.015)

    total = line_h * len(lines) + sub_h
    y = h - margin - total if layout == "thumb" else h - int(h * 0.07) - total
    stroke = max(2, size // 14)
    for ln in lines:
        tw = text_width(ln, size)
        draw_text(draw, ((w - tw) / 2, y), ln, size, (255, 235, 59), stroke, (0, 0, 0))
        y += line_h
    if sub_lines:
        y += int(h * 0.015)
        for ln in sub_lines:
            tw = text_width(ln, sub_size)
            draw_text(draw, ((w - tw) / 2, y), ln, sub_size, (255, 255, 255), max(1, stroke // 2), (0, 0, 0))
            y += sub_lh
    return _to_jpeg(img)


def caption_png(
    text: str, width: int, height: int, size: int, max_lines: int = 3,
    highlight: int | None = None, valign: str = "bottom", hl_color=(255, 214, 0),
) -> bytes:
    """Transparent PNG (width x height) with a caption, for video overlays.

    highlight = index of the word (counted across lines) to colour, for karaoke-style captions.
    valign = "bottom" or "top".
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = int(width * 0.07)
    s, lines, line_h = fit(text.strip(), width - 2 * margin, height - 16, size, max(14, size // 2), max_lines)
    block_h = line_h * len(lines)
    pad = int(s * 0.45)
    y0 = 8 + pad if valign == "top" else height - block_h - 8
    widest = max((text_width(ln, s) for ln in lines), default=0)
    box = (int((width - widest) / 2) - pad, y0 - pad // 2, int((width + widest) / 2) + pad, y0 + block_h + pad // 2)
    draw.rounded_rectangle(box, radius=pad, fill=(0, 0, 0, 150))
    stroke = max(2, s // 16)
    y = y0
    k = 0
    for ln in lines:
        tw = text_width(ln, s)
        if highlight is None:
            draw_text(draw, ((width - tw) / 2, y), ln, s, (255, 255, 255), stroke, (0, 0, 0))
        else:
            x = (width - tw) / 2
            space = text_width(" ", s)
            for word in ln.split(" "):
                fill = hl_color if k == highlight else (255, 255, 255)
                draw_text(draw, (x, y), word, s, fill, stroke, (0, 0, 0))
                x += text_width(word, s) + space
                k += 1
        y += line_h
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def upscale(data: bytes, factor: int = 2) -> bytes:
    """Lanczos upscale + light sharpen (no AI). Output JPEG, long side capped at 4096."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    w, h = img.size
    f = max(1, min(factor, MAX_SIDE // max(w, h))) if max(w, h) * factor > MAX_SIDE else factor
    if f <= 1:
        f = 1
    img = img.resize((w * f, h * f), Image.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
    return _to_jpeg(img, 95)


def image_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.size
