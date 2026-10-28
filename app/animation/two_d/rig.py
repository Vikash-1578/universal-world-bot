"""Auto-rig for a cut-out character: split it into head / body / legs so parts can move on their own.

    neck  = narrowest row in the upper part of the picture   -> head layer above it (tilts, mouth shapes)
    legs  = rows near the bottom with two separate pieces   -> left / right leg layers (swing while walking)
    pose  = whole-body variants ("point", "wave", "explain") -> body layer (arm gestures)
    mouth = the area that differs between the base and the "talk" picture -> pasted on any face (open / half)

If something is not found (long dress, no talk picture...) that part simply does not move.
"""
from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

GESTURES = ("point", "wave", "explain")


def _runs(row: list[int], min_len: int) -> list[tuple[int, int]]:
    out, start = [], None
    for x, v in enumerate(row + [0]):
        if v > 128 and start is None:
            start = x
        elif v <= 128 and start is not None:
            if x - start >= min_len:
                out.append((start, x))
            start = None
    return out


def _alpha_rows(alpha: Image.Image) -> list[list[int]]:
    w, h = alpha.size
    data = alpha.tobytes()
    return [list(data[y * w:(y + 1) * w]) for y in range(h)]


def find_neck(alpha: Image.Image) -> int:
    w, h = alpha.size
    rows = _alpha_rows(alpha)
    best, best_y = None, int(h * 0.25)
    for y in range(int(h * 0.12), int(h * 0.45)):
        r = _runs(rows[y], 2)
        if not r:
            continue
        width = max(b - a for a, b in r)  # the widest piece (ignores a separate hand next to the head)
        if best is None or width < best:
            best, best_y = width, y
    return best_y


def find_legs(alpha: Image.Image) -> tuple[int, int] | None:
    """(crotch row, split x) when the lower part has two separate legs."""
    w, h = alpha.size
    rows = _alpha_rows(alpha)
    min_len = max(2, int(w * 0.04))
    top = None
    for y in range(int(h * 0.97), int(h * 0.45), -1):
        r = _runs(rows[y], min_len)
        if len(r) >= 2:
            top = y
        elif top is not None and top - y > 2:
            break
    if top is None or (h * 0.97 - top) < h * 0.10:
        return None
    r = _runs(rows[min(h - 1, top + 3)], min_len)
    if len(r) < 2:
        return None
    gaps = [(r[i + 1][0] - r[i][1], (r[i][1] + r[i + 1][0]) // 2) for i in range(len(r) - 1)]
    _, split = max(gaps)
    return top, split


def mouth_box(base_head: Image.Image, talk_head: Image.Image) -> tuple[int, int, int, int] | None:
    a = base_head.convert("RGB")
    b = talk_head.convert("RGB").resize(a.size)
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 60 else 0)
    w, h = diff.size
    diff = diff.crop((0, int(h * 0.35), w, h))
    box = diff.getbbox()
    if not box:
        return None
    x0, y0, x1, y1 = box
    y0, y1 = y0 + int(h * 0.35), y1 + int(h * 0.35)
    if (x1 - x0) * (y1 - y0) > w * h * 0.25:  # whole face changed -> not just a mouth
        return None
    pad = max(2, int(w * 0.02))
    return max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)


def find_mouth(head: Image.Image) -> tuple[tuple[int, int, int, int], str] | None:
    """Locate the mouth on a single front-facing cartoon head (no 'talk' picture needed).

    Looks in the lower-middle of the face for a dark or red, wider-than-tall mark (the drawn mouth line / smile),
    away from the outline. Returns (box, "found") or, if nothing reliable is seen, an estimated box with "estimated".
    None when the head is too small to animate."""
    h = head.convert("RGBA")
    w, hh = h.size
    if w < 24 or hh < 24:
        return None
    a = h.getchannel("A")
    inside = a.point(lambda v: 255 if v > 200 else 0).filter(ImageFilter.MinFilter(max(3, (min(w, hh) // 18) | 1)))
    box = inside.getbbox()
    if not box:
        return None
    fx0, fy0, fx1, fy1 = box
    fw, fh = fx1 - fx0, fy1 - fy0
    cx = (fx0 + fx1) / 2
    x0, x1 = int(cx - fw * 0.28), int(cx + fw * 0.28)
    y0, y1 = int(fy0 + fh * 0.55), int(fy0 + fh * 0.92)
    px, ins = h.load(), inside.load()
    pts = [px[x, y][:3] for y in range(max(0, y0), min(hh, y1), 3) for x in range(max(0, x0), min(w, x1), 3) if ins[x, y]]
    if not pts:
        return None
    skin = tuple(sorted(c[i] for c in pts)[len(pts) // 2] for i in range(3))  # median colour of the lower face
    skin_l = sum(skin) / 3
    mark = Image.new("L", (w, hh), 0)
    md = mark.load()
    for y in range(max(0, y0), min(hh, y1)):
        for x in range(max(0, x0), min(w, x1)):
            if not ins[x, y]:
                continue
            r, g, b, _ = px[x, y]
            diff = sum(abs(c - s) for c, s in zip((r, g, b), skin))
            dark = diff > 110 and (r + g + b) / 3 < skin_l - 35  # mouth line / dark lips
            lips = diff > 60 and r > 150 and r > g + 60 and r > b + 40  # pink / red lips (also inside a beard)
            if dark or lips:
                md[x, y] = 255
    best = None
    for y in range(max(0, y0), min(hh, y1), 2):
        for x in range(max(0, x0), min(w, x1), 2):
            if md[x, y] != 255:
                continue
            ImageDraw.floodfill(mark, (x, y), 100)
            comp = mark.point(lambda v: 255 if v == 100 else 0)
            mark.paste(50, mask=comp)
            bb = comp.getbbox()
            if not bb:
                continue
            bw, bh = bb[2] - bb[0], bb[3] - bb[1]
            if not (fw * 0.07 <= bw <= fw * 0.5 and bh <= fh * 0.18 and bw >= bh) or bb[3] >= y1 - 1 or bb[1] <= y0:
                continue  # eyes / glasses / beard / outline / collar pieces (touching the search edge)
            dist = abs((bb[0] + bb[2]) / 2 - cx) + abs((bb[1] + bb[3]) / 2 - (fy0 + fh * 0.74)) * 0.5
            if best is None or dist < best[0]:
                best = (dist, bb)
    if best:
        return best[1], "found"
    mw = fw * 0.2
    my = fy0 + fh * 0.78
    return (int(cx - mw / 2), int(my - fh * 0.02), int(cx + mw / 2), int(my + fh * 0.02)), "estimated"


def draw_mouth(head: Image.Image, box: tuple[int, int, int, int], level: float) -> Image.Image:
    """Open the drawn mouth: a dark mouth opening with a tongue, its height follows the voice (0..1)."""
    out = head.copy()
    x0, y0, x1, y1 = box
    w = max(6, int((x1 - x0) * 0.9), int(head.width * 0.09))
    cx, top = (x0 + x1) / 2, (y0 + y1) / 2 - 1
    hgt = max(2, int(level * min(head.height * 0.08, w * 0.6)))
    d = ImageDraw.Draw(out)
    lw = max(1, w // 14)
    d.ellipse((cx - w / 2, top, cx + w / 2, top + hgt), fill=(70, 18, 28, 255), outline=(35, 10, 12, 255), width=lw)
    if hgt > 6:
        d.ellipse((cx - w * 0.28, top + hgt * 0.5, cx + w * 0.28, top + hgt - lw), fill=(205, 85, 95, 255))
    return out


class Rig:
    def __init__(self, base: Image.Image, variants: dict[str, Image.Image]) -> None:
        self.base = base.convert("RGBA")
        self.w, self.h = self.base.size
        self.var = {k: v.convert("RGBA").resize(self.base.size) for k, v in variants.items() if v is not None}
        alpha = self.base.getchannel("A")
        self.neck = find_neck(alpha)
        self.head_bottom = min(self.h, self.neck + max(2, int(self.h * 0.03)))
        self.legs = find_legs(alpha)
        self.pad = int(max(self.w, self.h) * 0.12)
        self.cw, self.ch = self.w + 2 * self.pad, self.h + self.pad
        self.cache: dict[tuple, Image.Image] = {}
        # mouth patch from the talk picture
        self.mouth = None
        self.mouth_source = ""  # "talk-image" (owner's talk picture) | "found" | "estimated" | "" (cannot animate)
        self.auto_mouth: tuple[int, int, int, int] | None = None
        if "talk" in self.var:
            bh = self.base.crop((0, 0, self.w, self.head_bottom))
            th = self.var["talk"].crop((0, 0, self.w, self.head_bottom))
            box = mouth_box(bh, th)
            if box:
                self.mouth = (box, th.crop(box))
                self.mouth_source = "talk-image"
        if self.mouth is None:
            fm = find_mouth(self.base.crop((0, 0, self.w, self.head_bottom)))
            if fm:
                self.auto_mouth, self.mouth_source = fm

    # ---------------------------------------------------------------- layers
    def _head(self, face: str, mouth: str) -> Image.Image:
        src = self.var.get(face, self.base) if face != "base" else self.base
        head = src.crop((0, 0, self.w, self.head_bottom)).copy()
        if mouth != "closed" and self.mouth is not None:
            (x0, y0, x1, y1), patch = self.mouth
            if mouth == "half":
                ph = max(1, int(patch.height * 0.55))
                head.alpha_composite(patch.resize((patch.width, ph)), (x0, y0))
            else:
                head.alpha_composite(patch, (x0, y0))
        elif mouth != "closed" and self.auto_mouth is not None:
            head = draw_mouth(head, self.auto_mouth, 0.5 if mouth == "half" else 1.0)
        return head

    def _body(self, pose: str) -> Image.Image:
        src = self.var.get(pose, self.base)
        body = src.copy()
        # clear the head area (the head layer is drawn on top); keep a little neck overlap
        clear = Image.new("RGBA", (self.w, max(0, self.neck - 2)), (0, 0, 0, 0))
        body.paste(clear, (0, 0))
        return body

    def has_legs(self) -> bool:
        return self.legs is not None

    def has_mouth(self) -> bool:
        return self.mouth is not None or self.auto_mouth is not None

    def compose(self, pose: str = "base", face: str = "base", mouth: str = "closed", leg: int = 0, tilt: float = 0) -> Image.Image:
        """Character picture on a padded canvas; feet stay on the bottom edge, centre stays at cw/2."""
        tilt = round(tilt * 2) / 2  # 0.5 degree steps keep the cache small and motion smooth
        key = (pose, face, mouth, leg, tilt)
        img = self.cache.get(key)
        if img is not None:
            return img
        canvas = Image.new("RGBA", (self.cw, self.ch), (0, 0, 0, 0))
        ox, oy = self.pad, self.pad
        body = self._body(pose)
        if leg and self.legs is not None:
            crotch, split = self.legs
            top = max(0, crotch - 4)
            upper = body.copy()
            upper.paste(Image.new("RGBA", (self.w, self.h - top), (0, 0, 0, 0)), (0, top))
            canvas.alpha_composite(upper, (ox, oy))
            for side, (x0, x1), sign in (("l", (0, split), 1), ("r", (split, self.w), -1)):
                part = Image.new("RGBA", (self.cw, self.ch), (0, 0, 0, 0))
                part.alpha_composite(body.crop((x0, top, x1, self.h)), (ox + x0, oy + top))
                pivot = (ox + (x0 + x1) / 2, oy + crotch)
                part = part.rotate(sign * leg * 4, resample=Image.BICUBIC, center=pivot)
                canvas.alpha_composite(part)
        else:
            canvas.alpha_composite(body, (ox, oy))
        head = self._head(face, mouth)
        if tilt:
            layer = Image.new("RGBA", (self.cw, self.ch), (0, 0, 0, 0))
            layer.alpha_composite(head, (ox, oy))
            layer = layer.rotate(tilt, resample=Image.BICUBIC, center=(ox + self.w / 2, oy + self.neck))
            canvas.alpha_composite(layer)
        else:
            canvas.alpha_composite(head, (ox, oy))
        if len(self.cache) < 600:
            self.cache[key] = canvas
        return canvas


def leg_phase(t: float, speed: float = 2.2) -> int:
    """-2..2 swing step for walking."""
    return int(round(2 * math.sin(t * math.pi * speed)))
