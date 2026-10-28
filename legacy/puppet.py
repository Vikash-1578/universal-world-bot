"""Puppet animation: cut-out characters on a background that walk in, talk (bounce with the voice), with camera moves.

Pure Pillow + ffmpeg (frames are piped to ffmpeg), so it runs on a small free server:
    key_sprite()      AI picture on a plain green background -> transparent character (RGBA)
    grade()           mood colour grading (day / sunset / night / indoor / spooky)
    envelope()        loudness per video frame from a wav (drives the "talking" bounce)
    render_puppet()   one scene -> mp4 (frames + audio + caption track)
"""
from __future__ import annotations

import io
import math
import subprocess
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from app.services.media import VideoError, ffmpeg_exe

SIZES = {"small": 0.38, "medium": 0.58, "big": 0.72}
MOODS = ("day", "sunset", "night", "indoor", "spooky")
CAMERAS = ("zoom_in", "pan_right", "static", "zoom_out", "pan_left")
STAGE = 1.14  # stage is 14% bigger than the frame so the camera can move


# ---------------------------------------------------------------- sprites
def key_sprite(data: bytes, max_side: int = 900, thresh: int = 70, crop: bool = True) -> Image.Image | None:
    """Remove the plain background that touches the picture border. None if it does not look like a cut-out."""
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    im.thumbnail((max_side, max_side))
    w, h = im.size
    work = im.copy()
    c0 = im.getpixel((0, 0))
    edge = [im.getpixel((int((w - 1) * k / 16), y)) for k in range(17) for y in (0, h - 1)]
    edge += [im.getpixel((x, int((h - 1) * k / 16))) for k in range(17) for x in (0, w - 1)]
    near = sum(1 for p in edge if sum(abs(a - b) for a, b in zip(p, c0)) < 90)
    if near < len(edge) * 0.85:  # border is not one plain colour -> not a cut-out picture
        return None
    mark = tuple(255 - v if abs(255 - 2 * v) > 60 else (0 if v > 127 else 255) for v in c0)  # far from the background
    pts = []
    for k in range(9):
        pts += [(int((w - 1) * k / 8), 0), (int((w - 1) * k / 8), h - 1), (0, int((h - 1) * k / 8)), (w - 1, int((h - 1) * k / 8))]
    for p in pts:
        if work.getpixel(p) != mark:
            ImageDraw.floodfill(work, p, mark, thresh=thresh)
    r0, g0, b0 = ImageChops.difference(work, Image.new("RGB", (w, h), mark)).split()
    diff = ImageChops.lighter(ImageChops.lighter(r0, g0), b0)
    alpha = diff.point(lambda v: 255 if v > 0 else 0)
    transparent = alpha.histogram()[0] / float(w * h)
    if not 0.22 <= transparent <= 0.94:
        return None
    alpha = alpha.filter(ImageFilter.MinFilter(3))
    band = ImageChops.subtract(alpha.filter(ImageFilter.MaxFilter(7)), alpha.filter(ImageFilter.MinFilter(7)))
    r, g, b = im.split()
    g2 = Image.composite(ImageChops.darker(g, ImageChops.lighter(r, b)), g, band)  # remove green fringe
    out = Image.merge("RGBA", (r, g2, b, alpha.filter(ImageFilter.GaussianBlur(0.7))))
    box = alpha.getbbox()
    if not box:
        return None
    if not crop:
        return out
    out = out.crop(box)
    if out.width < 20 or out.height < 40:
        return None
    return out


def sprite_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- mood
def grade(img: Image.Image, mood: str, strength: float = 1.0) -> Image.Image:
    mood = (mood or "day").lower()
    if mood not in MOODS or mood == "day":
        return img
    mode = img.mode
    base = img.convert("RGB")
    if mood == "sunset":
        tint, amt, bright, sat = (255, 140, 60), 0.18, 1.0, 1.1
    elif mood == "night":
        tint, amt, bright, sat = (30, 50, 120), 0.35, 0.55, 0.8
    elif mood == "indoor":
        tint, amt, bright, sat = (255, 210, 150), 0.10, 0.97, 1.0
    else:  # spooky
        tint, amt, bright, sat = (40, 90, 80), 0.30, 0.6, 0.5
    amt *= strength
    out = ImageEnhance.Color(base).enhance(1 + (sat - 1) * strength)
    out = ImageEnhance.Brightness(out).enhance(1 + (bright - 1) * strength)
    out = Image.blend(out, Image.new("RGB", out.size, tint), amt)
    if mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(img.getchannel("A"))
    return out


# ---------------------------------------------------------------- audio
def envelope(wav_path: Path, fps: int) -> list[float]:
    """0..1 loudness for each video frame."""
    with wave.open(str(wav_path), "rb") as wf:
        rate, ch, width = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if width != 2:
        return []
    a = array("h")
    a.frombytes(raw)
    if ch > 1:
        a = a[::ch]
    step = max(1, rate // fps)
    vals = []
    for i in range(0, len(a), step):
        chunk = a[i:i + step:4]
        vals.append(math.sqrt(sum(x * x for x in chunk) / max(1, len(chunk))) if chunk else 0.0)
    peak = max(vals) if vals else 0.0
    return [min(1.0, v / peak * 1.4) for v in vals] if peak > 0 else vals


# ---------------------------------------------------------------- scene model
EMOTIONS = ("happy", "sad", "angry", "scared", "surprised")
ACTIONS = ("jump", "shake", "nod", "point", "wave", "explain")
FADE = 0.25  # seconds of fade in/out per scene


@dataclass
class Actor:
    id: str
    sprite: Image.Image  # the base pose
    size: str = "medium"
    x: float = 0.5  # target position, fraction of stage width
    enter: str | None = None  # "left" | "right" | None
    variants: dict[str, Image.Image] = field(default_factory=dict)  # "talk", "blink", emotions
    flip: bool = False  # mirror (sprites are drawn turned to the right)


@dataclass
class Talk:
    actor: str
    start: float
    end: float
    emotion: str = ""
    action: str = ""


@dataclass
class PuppetScene:
    background: Image.Image
    actors: list[Actor]
    talks: list[Talk]
    duration: float
    camera: str = "static"
    mood: str = "day"
    env: list[float] = field(default_factory=list)
    fade: bool = True


def layout(n: int) -> list[float]:
    if n <= 0:
        return []
    if n == 1:
        return [0.5]
    lo, hi = (0.28, 0.72) if n == 2 else (0.2, 0.8)
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / img.width, h / img.height)
    im = img.convert("RGB").resize((max(w, int(img.width * s + 0.5)), max(h, int(img.height * s + 0.5))), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


class Stage:
    """Pre-scaled, rigged characters for one scene; each frame = background + composed characters + camera."""

    def __init__(self, sc: PuppetScene, w: int, h: int, fps: int) -> None:
        from app.services.rig import Rig

        self.sc, self.w, self.h, self.fps = sc, w, h, fps
        self.sw, self.sh = int(w * STAGE), int(h * STAGE)
        self.bg = grade(_cover(sc.background, self.sw, self.sh), sc.mood)
        self.ground = int(self.sh * 0.95)
        self.walk = min(1.6, max(0.6, sc.duration * 0.25))
        self.black = Image.new("RGB", (w, h), (0, 0, 0))
        self.rigs: dict[str, Rig] = {}
        self.heights: dict[str, int] = {}
        self.lean: dict[tuple, Image.Image] = {}
        for a in sc.actors:
            th = int(min(self.sh * SIZES.get(a.size, SIZES["medium"]), self.sh * 0.9))

            def prep(img: Image.Image) -> Image.Image:
                sp = img.convert("RGBA")
                sp = sp.resize((max(1, int(sp.width * th / sp.height)), th), Image.LANCZOS)
                sp = grade(sp, sc.mood, 0.6)
                return sp.transpose(Image.FLIP_LEFT_RIGHT) if a.flip else sp

            self.rigs[a.id] = Rig(prep(a.sprite), {k: prep(v) for k, v in a.variants.items() if v is not None})
            self.heights[a.id] = th
        # talk index -> shot ("close" / "medium"); short lines stay wide
        self.shots = {}
        n = 0
        for k in sc.talks:
            if k.end - k.start >= 1.0:
                self.shots[id(k)] = "close" if n % 3 != 2 else "medium"
                n += 1
        env = sc.env or []
        self.env = [max(env[max(0, i - 1):i + 2]) if env else 0.0 for i in range(len(env))]  # smoothed

    def talk_at(self, t: float) -> Talk | None:
        for k in self.sc.talks:
            if k.start <= t < k.end:
                return k
        return None

    def emotion_of(self, actor: str, t: float) -> str:
        """Face from the actor's latest line so far (stays until the scene ends)."""
        emo = ""
        for k in self.sc.talks:
            if k.actor == actor and k.start <= t:
                emo = k.emotion
        return emo

    def _leaned(self, img: Image.Image, key: tuple, angle: int) -> Image.Image:
        if not angle:
            return img
        k = key + (angle,)
        out = self.lean.get(k)
        if out is None:
            out = img.rotate(angle, resample=Image.BICUBIC, center=(img.width / 2, img.height))
            if len(self.lean) < 200:
                self.lean[k] = out
        return out

    def frame(self, t: float, idx: int) -> Image.Image:
        from app.services.rig import leg_phase

        sc = self.sc
        canvas = self.bg.copy()
        tk = self.talk_at(t)
        env = self.env[idx] if idx < len(self.env) else 0.0
        boxes: dict[str, tuple[float, float, float]] = {}
        for i, a in enumerate(sc.actors):
            rig = self.rigs[a.id]
            tx = a.x * self.sw
            dx = 0.0
            dy = math.sin(t * math.pi + i) * self.sh * 0.004  # breathing
            emo = self.emotion_of(a.id, t)
            face = emo if emo in rig.var else "base"
            pose, mouth, leg, tilt, lean = "base", "closed", 0, 0, 0
            walking = bool(a.enter and t < self.walk)
            if walking:
                p = _ease(t / self.walk)
                start = -rig.cw * 0.6 if a.enter == "left" else self.sw + rig.cw * 0.6
                tx = start + (tx - start) * p
                if rig.has_legs():
                    leg = leg_phase(t)
                    dy = -abs(math.sin(t * math.pi * 2.2)) * self.sh * 0.008
                else:
                    step = math.sin(t * math.pi * 4)
                    dy = -abs(step) * self.sh * 0.025
                    lean = 3 if step > 0 else -3
            if tk is not None and tk.actor == a.id:
                lt = t - tk.start
                span = max(0.1, tk.end - tk.start)
                if rig.has_mouth():
                    mouth = "open" if env > 0.55 else "half" if env > 0.22 else "closed"
                else:
                    dy -= env * self.sh * 0.02
                tilt = int(round(1.6 * math.sin(t * 2.6 + i)))
                act = tk.action
                if act == "wave" and "wave" in rig.var:
                    pose = "wave" if int(lt / 0.3) % 2 == 0 else "base"
                elif act in ("point", "explain") and act in rig.var:
                    pose = act
                elif not act and "explain" in rig.var and 0.2 * span < lt < 0.8 * span and int(tk.start * 10) % 2 == 1:
                    pose = "explain"
                if act == "jump" and lt < 0.7:
                    dy -= math.sin(math.pi * lt / 0.7) * self.sh * 0.09
                elif act == "shake" and lt < 1.2:
                    dx = math.sin(lt * 45) * self.sw * 0.006
                elif act == "nod" and lt < 0.9:
                    tilt = int(round(4 * math.sin(lt * math.pi * 3.3)))
            elif not walking and "blink" in rig.var and face == "base" and (t + i * 1.3) % 3.7 < 0.13:
                face = "blink"
            if emo == "scared" and not walking:
                dx += math.sin(t * 60 + i) * self.sw * 0.002
            key = (pose, face, mouth, leg, tilt)
            img = self._leaned(rig.compose(*key), key, lean)
            x = int(tx + dx - img.width / 2)
            y = int(self.ground - img.height + dy)
            canvas.paste(img, (x, y), img)
            boxes[a.id] = (tx + dx, self.ground - self.heights[a.id] + dy, self.heights[a.id])
        out = self._camera(canvas, t, tk, boxes)
        if sc.fade:
            if t < FADE:
                out = Image.blend(self.black, out, max(0.0, t / FADE))
            elif t > sc.duration - FADE:
                out = Image.blend(self.black, out, max(0.0, (sc.duration - t) / FADE))
        return out

    def _wide(self, t: float) -> tuple[float, float, float, float]:
        p = _ease(t / max(0.1, self.sc.duration))
        cam = self.sc.camera
        if cam == "zoom_in":
            z = 1.0 + 0.12 * p
        elif cam == "zoom_out":
            z = 1.12 - 0.12 * p
        else:
            z = 1.06
        cw, ch = self.sw / z, self.sh / z
        cx = self.sw / 2
        if cam == "pan_right":
            cx = cw / 2 + (self.sw - cw) * p
        elif cam == "pan_left":
            cx = self.sw - cw / 2 - (self.sw - cw) * p
        return cx, self.sh - ch / 2, cw, ch

    def _camera(self, canvas: Image.Image, t: float, tk: Talk | None = None, boxes: dict | None = None) -> Image.Image:
        cx, cy, cw, ch = self._wide(t)
        shot = self.shots.get(id(tk)) if tk is not None else None
        if shot and boxes and tk.actor in boxes:
            ax, atop, ah = boxes[tk.actor]
            want_h = ah * (1.05 if shot == "close" else 1.6)
            z = max(1.15, min(2.3 if shot == "close" else 1.6, self.sh / max(1.0, want_h)))
            zw, zh = self.sw / z, self.sh / z
            zx = min(max(ax, zw / 2), self.sw - zw / 2)
            zy = min(max(atop - 0.06 * zh + zh / 2, zh / 2), self.sh - zh / 2)
            k = _ease(min(1.0, (t - tk.start) / 0.3, (tk.end - t) / 0.3))
            cx, cy, cw, ch = (cx + (zx - cx) * k, cy + (zy - cy) * k, cw + (zw - cw) * k, ch + (zh - ch) * k)
        box = (int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2))
        return canvas.crop(box).resize((self.w, self.h), Image.BILINEAR)


def render_puppet(sc: PuppetScene, w: int, h: int, fps: int, out: Path, audio: Path,
                  track: Path | None = None, cap_y: int = 0, timeout: float = 1200.0) -> Path:
    """Blocking: draw every frame with Pillow, pipe to ffmpeg with the scene audio and caption track."""
    stage = Stage(sc, w, h, fps)
    n = max(1, int(round(sc.duration * fps)))
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-i", str(audio)]
    parts = []
    if track is not None:
        cmd += ["-f", "concat", "-safe", "0", "-i", str(track)]
        parts.append(f"[2:v]format=rgba,fps={fps}[cap];[0:v][cap]overlay=x=0:y={cap_y}:eof_action=pass:format=auto[vc]")
        parts.append("[vc]format=yuv420p[vout]")
    else:
        parts.append("[0:v]format=yuv420p[vout]")
    parts.append("[1:a]aresample=44100,apad[a]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[a]", "-t", f"{sc.duration:.3f}",
            "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        assert proc.stdin is not None
        for i in range(n):
            proc.stdin.write(stage.frame(i / fps, i).tobytes())
        proc.stdin.close()
        _, err = proc.communicate(timeout=timeout)
    except (BrokenPipeError, OSError) as e:
        _, err = proc.communicate(timeout=60)
        raise VideoError("ffmpeg (puppet) band ho gaya: " + (err or b"").decode("utf-8", "ignore")[-300:]) from e
    except subprocess.TimeoutExpired as e:
        proc.kill()
        raise VideoError("puppet render bahut lamba chala") from e
    if proc.returncode != 0:
        raise VideoError("ffmpeg (puppet) error: " + (err or b"").decode("utf-8", "ignore")[-300:])
    return out


def preview(sc: PuppetScene, w: int, h: int, t: float = 0.0) -> Image.Image:
    """One frame (used for thumbnails and tests)."""
    return Stage(sc, w, h, 25).frame(t, int(t * 25))
