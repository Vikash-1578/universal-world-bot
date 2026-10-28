"""Captions: word timings, karaoke-style highlight states, and one overlay track per video.

A "track" is an ffconcat list of transparent PNGs (blank PNG in the gaps), so ffmpeg needs a
single extra input however many captions there are.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.services.image_compose import caption_png


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


PUNCT_END = ",.!?;:।"


def estimate_words(text: str, seconds: float, offset: float = 0.0) -> list[Word]:
    """Spread the words over `seconds` in proportion to their length."""
    words = text.split()
    if not words or seconds <= 0:
        return []
    weights = [max(1, len(w)) + (3 if w[-1:] in PUNCT_END else 0) for w in words]
    total = float(sum(weights))
    out, t = [], offset
    for w, wt in zip(words, weights):
        d = seconds * wt / total
        out.append(Word(w, t, t + d))
        t += d
    return out


def align_words(narration: str, timed: list[Word], seconds: float) -> list[Word]:
    """Show the narration's own words, timed by a speech-to-text pass (counts may differ)."""
    words = narration.split()
    if not words:
        return []
    timed = [w for w in timed if w.end > w.start]
    if not timed:
        return estimate_words(narration, seconds)
    if len(timed) == len(words):
        return [Word(t, w.start, w.end) for t, w in zip(words, timed)]
    a, b = timed[0].start, max(timed[-1].end, timed[0].start + 0.1)
    return estimate_words(narration, b - a, a)


def group_words(words: list[Word], max_words: int) -> list[list[Word]]:
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or (w.text[-1:] in PUNCT_END and len(cur) >= max(2, max_words // 2)):
            groups.append(cur)
            cur = []
    if cur:
        if groups and len(cur) == 1:
            groups[-1].extend(cur)
        else:
            groups.append(cur)
    return groups


State = tuple[float, float, "int | None", str]  # start, end, highlighted word index (None = plain), text


def caption_states(words: list[Word], max_words: int, mode: str = "word") -> list[State]:
    groups = group_words(words, max_words)
    states: list[State] = []
    prev_end = 0.0
    for gi, g in enumerate(groups):
        text = " ".join(w.text for w in g)
        nxt = groups[gi + 1][0].start if gi + 1 < len(groups) else None
        g_end = g[-1].end + 0.12
        if nxt is not None:
            g_end = min(g_end, nxt)
        if mode == "plain":
            a = max(prev_end, g[0].start - 0.05)
            states.append((a, max(g_end, a + 0.1), None, text))
            prev_end = states[-1][1]
            continue
        for k, w in enumerate(g):
            a = max(prev_end, w.start - 0.05 if k == 0 else w.start)
            b = g[k + 1].start if k + 1 < len(g) else g_end
            b = max(b, a + 0.05)
            states.append((a, b, k, text))
            prev_end = b
    return states


def srt_time(sec: float) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(words: list[Word], max_words: int, offset: float = 0.0, start_index: int = 1) -> tuple[str, int]:
    """SRT text for the chunk-level captions of `words` (shifted by offset). Returns (text, next_index)."""
    lines: list[str] = []
    n = start_index
    for a, b, _, text in caption_states(words, max_words, "plain"):
        lines += [str(n), f"{srt_time(offset + a)} --> {srt_time(offset + b)}", text, ""]
        n += 1
    return "\n".join(lines), n


def _png_bytes_blank(w: int, h: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (w, h), (0, 0, 0, 0)).save(out, "PNG")
    return out.getvalue()


def write_track(
    states: list[State], total: float, width: int, height: int, size: int,
    workdir: Path, name: str, valign: str = "bottom",
) -> Path | None:
    """Write PNGs + an ffconcat list covering 0..total. Returns the list path (None if no captions)."""
    if not states:
        return None
    blank = workdir / f"{name}_blank.png"
    blank.write_bytes(_png_bytes_blank(width, height))
    cache: dict[tuple, Path] = {}
    entries: list[tuple[Path, float]] = []
    t = 0.0

    def add(p: Path, d: float) -> None:
        if d > 0.001:
            entries.append((p, d))

    for a, b, hl, text in states:
        a, b = max(a, t), min(b, total)
        if b <= a:
            continue
        add(blank, a - t)
        key = (text, hl)
        if key not in cache:
            p = workdir / f"{name}_{len(cache)}.png"
            p.write_bytes(caption_png(text, width, height, size, highlight=hl, valign=valign))
            cache[key] = p
        add(cache[key], b - a)
        t = b
    add(blank, total - t)
    if not entries:
        return None
    lines = ["ffconcat version 1.0"]
    for p, d in entries:
        lines += [f"file '{str(p).replace(chr(92), '/')}'", f"duration {d:.3f}"]
    lines.append(f"file '{str(entries[-1][0]).replace(chr(92), '/')}'")
    lst = workdir / f"{name}.ffconcat"
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lst
