"""Turn a written script into structure WITHOUT AI (deterministic, works offline).

Understood format (Hindi / English / Hinglish):
    Title: Kachhua aur Khargosh 2.0
    [Scene 1: Jungle ka race track, subah]        <- scene header ("Scene 2 -", "दृश्य 3:", "# ..." also work)
    Narrator: Sab jaante hain...                    <- narration
    Khargosh: (gusse me) Is baar main jeetunga!     <- dialogue, "(gusse me)" = emotion / direction
    (Khargosh tezi se bhaagta hai)                  <- stage direction / action
Plain paragraphs without "Name:" become narration. A script with no scene headers is split every few lines.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

NARRATOR_NAMES = {"narrator", "narration", "kathavachak", "kathavaachak", "sutradhar", "कथावाचक", "सूत्रधार", "वाचक", "voiceover", "vo",
                  "नैरेटर", "नरेटर", "कथाकार", "वर्णनकर्ता"}
SCENE_WORDS = r"scene|seen|drishya|दृश्य|सीन|सीन्स|द्रश्य"
_SCENE_RE = re.compile(r"^\s*(?:\[\s*)?(?:scene|seen|drishya|दृश्य|सीन|द्रश्य|sc\.?|#+)\s*([\d०-९]+)?\s*[:.\-–)]*\s*(.*?)\s*\]?\s*$", re.I)
_TITLE_RE = re.compile(r"^\s*(?:title|naam|शीर्षक)\s*[:\-]\s*(.+)$", re.I)
_LINE_RE = re.compile(r"^\s*([^\s:：()\[\]][^:：()\[\]]{0,28}?)\s*(?:[\(（]([^)）]{1,60})[\)）])?\s*[:：]\s*(.+)$")
_PAREN_RE = re.compile(r"^\s*[\(\[]\s*([^)\]]{1,80})\s*[\)\]]\s*")
WORDS_PER_SEC = 2.4


@dataclass
class Line:
    kind: str           # "dialogue" | "narration" | "action"
    text: str
    speaker: str = ""
    direction: str = ""  # "(gusse me)" etc.


@dataclass
class ParsedScene:
    number: int
    heading: str = ""
    lines: list[Line] = field(default_factory=list)

    @property
    def characters(self) -> list[str]:
        seen: list[str] = []
        for ln in self.lines:
            if ln.kind == "dialogue" and ln.speaker not in seen:
                seen.append(ln.speaker)
        return seen

    @property
    def seconds(self) -> float:
        words = sum(len(ln.text.split()) for ln in self.lines if ln.kind != "action")
        return round(max(3.0, words / WORDS_PER_SEC + 0.6 * len(self.lines)), 1)


@dataclass
class ParsedScript:
    title: str
    scenes: list[ParsedScene]

    @property
    def characters(self) -> list[str]:
        out: list[str] = []
        for sc in self.scenes:
            for c in sc.characters:
                if c not in out:
                    out.append(c)
        return out

    @property
    def seconds(self) -> float:
        return round(sum(s.seconds for s in self.scenes), 1)

    def to_dict(self) -> dict:
        return {"title": self.title, "scenes": [asdict(s) for s in self.scenes], "characters": self.characters}


def _speaker(name: str) -> tuple[str, bool]:
    n = " ".join(name.split()).strip("*_ ")
    low = n.lower()
    # models sometimes mix scripts ("नarrator") — any form containing "arrat" counts as the narrator
    return n, low in NARRATOR_NAMES or "arrat" in low or low.endswith("rator")


def _is_scene_header(line: str) -> re.Match | None:
    s = line.strip()
    if not s:
        return None
    if s.startswith("[") and s.endswith("]") and re.search(rf"(?i){SCENE_WORDS}", s):
        return _SCENE_RE.match(s)
    if re.match(rf"(?i)^\s*({SCENE_WORDS})\s*[\d०-९]*\s*[:.\-–)]", s) or re.match(rf"(?i)^\s*({SCENE_WORDS})\s+[\d०-९]+\s*$", s):
        return _SCENE_RE.match(s)
    if s.startswith("#"):
        return _SCENE_RE.match(s)
    return None


def parse(text: str, max_lines_per_auto_scene: int = 6) -> ParsedScript:
    title = ""
    scenes: list[ParsedScene] = []
    current: ParsedScene | None = None
    had_headers = False
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or set(line) <= set("-=*_~"):
            continue
        m = _TITLE_RE.match(line)
        if m and not title and not scenes:
            title = m.group(1).strip()
            continue
        h = _is_scene_header(line)
        if h:
            had_headers = True
            current = ParsedScene(len(scenes) + 1, (h.group(2) or "").strip(" ]"))
            scenes.append(current)
            continue
        if current is None:
            current = ParsedScene(1)
            scenes.append(current)
        pm = _PAREN_RE.match(line)
        if pm and pm.end() >= len(line.rstrip()):
            current.lines.append(Line("action", pm.group(1).strip()))
            continue
        m = _LINE_RE.match(line)
        if m and not m.group(3).startswith("//") and not re.search(r"https?$", m.group(1).strip(), re.I):
            name, is_narr = _speaker(m.group(1))
            body = m.group(3).strip()
            direction = (m.group(2) or "").strip()
            dm = _PAREN_RE.match(body)
            if dm and not direction:
                direction, body = dm.group(1).strip(), body[dm.end():].strip()
            if body:
                current.lines.append(Line("narration" if is_narr else "dialogue", body, "" if is_narr else name, direction))
            continue
        current.lines.append(Line("narration", line))
    scenes = [s for s in scenes if s.lines]
    if not had_headers and scenes:  # no headers: split long text into scenes
        flat = [ln for s in scenes for ln in s.lines]
        scenes = [ParsedScene(i // max_lines_per_auto_scene + 1, "", flat[i:i + max_lines_per_auto_scene])
                  for i in range(0, len(flat), max_lines_per_auto_scene)]
    for i, s in enumerate(scenes, 1):
        s.number = i
    return ParsedScript(title, scenes)


def render(ps: ParsedScript) -> str:
    """Structure -> script text (same format the parser reads)."""
    out = [f"Title: {ps.title}"] if ps.title else []
    for s in ps.scenes:
        out.append(f"\n[Scene {s.number}{': ' + s.heading if s.heading else ''}]")
        for ln in s.lines:
            if ln.kind == "action":
                out.append(f"({ln.text})")
            elif ln.kind == "narration":
                out.append(f"Narrator: {ln.text}")
            else:
                out.append(f"{ln.speaker}: {'(' + ln.direction + ') ' if ln.direction else ''}{ln.text}")
    return "\n".join(out).strip() + "\n"
