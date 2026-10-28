"""Voice + lip-sync + body motion (the fix for the silent / static 2D video, 2026-10-28).

Real: Pillow renderer, FFmpeg, WAV timeline, validation. TEST DOUBLE: FakeTTS (tone pulses) unless a real Piper voice
is available (env UWB_PIPER_VOICES) — then `RealPiperTests` renders with the real Hindi voice too."""
import io
import math
import unittest
import wave
from array import array
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from app.animation.two_d import jobs as anim_jobs
from app.animation.two_d import puppet
from app.animation.two_d.rig import Rig, find_mouth
from app.audio import timeline as tl
from tests.helpers import FakeTTS, TempDirCase, make_hub, needs_ffmpeg, real_piper_dir
from tests.unit.test_library import background

STORY = """Title: Dost

[Scene 1: Jungle, subah]
Golu: (khush ho kar) Namaste dost, aaj hum khelenge!
Narrator: Dono dost hans pade.
Tortu: Haan, chalo khelte hain?
"""


def face_figure(shirt=(200, 60, 60)) -> bytes:
    """A cartoon figure drawn in the test: round face WITH a drawn mouth line, body, two legs, on white."""
    im = Image.new("RGB", (420, 900), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.ellipse((120, 30, 300, 230), fill=(205, 140, 100), outline=(40, 20, 10), width=5)        # face
    d.ellipse((165, 100, 190, 125), fill=(30, 20, 20))
    d.ellipse((230, 100, 255, 125), fill=(30, 20, 20))                                         # eyes
    d.arc((175, 150, 245, 195), 20, 160, fill=(60, 20, 15), width=5)                           # mouth (smile)
    d.rectangle((195, 228, 225, 260), fill=(205, 140, 100))                                    # neck
    d.rounded_rectangle((120, 258, 300, 560), 30, fill=shirt, outline=(40, 20, 10), width=4)    # body
    d.rectangle((135, 555, 195, 880), fill=(50, 60, 130))
    d.rectangle((225, 555, 285, 880), fill=(50, 60, 130))                                      # legs
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def tone_wav(path: Path, seconds: float, amp: int = 8000) -> Path:
    sr = 44100
    a = array("h", (int(amp * math.sin(2 * math.pi * 220 * i / sr)) for i in range(int(sr * seconds))))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())
    return path


class TimelineTests(TempDirCase):
    async def test_cues_follow_real_audio_and_lengths_match(self):
        lens = [1.0, 0.5, 2.0]
        lines = [{"speaker": "A", "text": "x", "actor": True}, {"speaker": "Narrator", "text": "y", "actor": False},
                 {"speaker": "B", "text": "z", "actor": True}]
        out = self.tmp / "scene.wav"
        res = tl.build_scene_audio(lines, 1.2, out, lambda i, ln: tone_wav(self.tmp / f"l{i}.wav", lens[i]), fps=30)
        c = res["cues"]
        self.assertAlmostEqual(c[0]["start"], 1.2, places=2)
        self.assertAlmostEqual(c[0]["end"] - c[0]["start"], 1.0, places=2)
        self.assertAlmostEqual(c[1]["start"], c[0]["end"] + tl.GAP, places=2)
        self.assertAlmostEqual(c[2]["end"] - c[2]["start"], 2.0, places=2)
        with wave.open(str(out)) as w:
            self.assertAlmostEqual(w.getnframes() / w.getframerate(), res["duration"], places=3)  # wav == timeline
        self.assertAlmostEqual(res["duration"] * 30, round(res["duration"] * 30), places=3)  # whole video frames
        self.assertGreater(tl.rms_db(out, c[0]["start"] + 0.1, c[0]["end"] - 0.1), -30)  # voice where the cue is
        self.assertLess(tl.rms_db(out, 0, 1.1), -100)  # silence before the first line
        srt = tl.build_srt(c)
        self.assertEqual(len(tl.parse_srt(srt)), 3)
        self.assertIn("A: x", srt)
        self.assertNotIn("Narrator: y", srt)


class MouthAndMotionTests(TempDirCase):
    def _stage(self, talks, duration=6.0, env=None, fps=12):
        from app.characters import imaging

        a = imaging.cutout(imaging.open_image(face_figure()))
        b = imaging.cutout(imaging.open_image(face_figure((60, 160, 60))))
        sc = puppet.PuppetScene(background=Image.open(io.BytesIO(background())).convert("RGB"),
                                actors=[puppet.Actor("Golu", a, x=0.3), puppet.Actor("Tortu", b, x=0.7)],
                                talks=talks, duration=duration, camera="static", env=env or [], fade=False)
        return puppet.Stage(sc, 640, 360, fps)

    async def test_mouth_found_on_single_picture(self):
        from app.characters import imaging

        cut = imaging.cutout(imaging.open_image(face_figure()))
        rig = Rig(cut, {})
        self.assertEqual(rig.mouth_source, "found")  # located on the drawing, not guessed
        x0, y0, x1, y1 = rig.auto_mouth
        self.assertTrue(40 < (x0 + x1) / 2 < 140 and 110 < (y0 + y1) / 2 < 190, rig.auto_mouth)
        closed, opened = rig.compose(mouth="closed"), rig.compose(mouth="open")
        diff = ImageChops.difference(closed.convert("RGB"), opened.convert("RGB")).getbbox()
        self.assertIsNotNone(diff)
        self.assertLess(diff[3], rig.pad + rig.head_bottom)  # only the head changes, body untouched
        self.assertIsNone(find_mouth(Image.new("RGBA", (10, 10))))

    async def test_speaker_mouth_moves_only_while_speaking(self):
        fps = 12
        env = [0.0] * (6 * fps)
        for i in range(int(1.0 * fps), int(3.0 * fps)):
            env[i] = 0.3 + 0.7 * abs(math.sin(i * 1.3))  # loud while Golu speaks
        st = self._stage([puppet.Talk("Golu", 1.0, 3.0, text="Namaste dost!")], env=env, fps=fps)
        during = [st.pose_at(i / fps, i) for i in range(int(1.1 * fps), int(2.9 * fps))]
        after = [st.pose_at(i / fps, i) for i in range(int(3.3 * fps), int(5.9 * fps))]
        opened = sum(1 for p in during if p["Golu"]["mouth"] != "closed")
        self.assertGreaterEqual(opened, len(during) * 0.6)
        self.assertTrue(all(p["Tortu"]["mouth"] == "closed" for p in during))  # listener's mouth stays shut
        self.assertTrue(all(p[k]["mouth"] == "closed" for p in after for k in ("Golu", "Tortu")))  # line over -> closed
        # visible: the speaker's head region in the frame differs between an open-mouth and a closed-mouth moment
        f_open = st.frame(next(i for i in range(int(1.1 * fps), int(2.9 * fps)) if st.pose_at(i / fps, i)["Golu"]["mouth"] == "open") / fps,
                          next(i for i in range(int(1.1 * fps), int(2.9 * fps)) if st.pose_at(i / fps, i)["Golu"]["mouth"] == "open"))
        self.assertIsNotNone(ImageChops.difference(f_open, st.frame(4.0, 48)).getbbox())

    async def test_body_moves_after_entry_without_pose_pictures(self):
        fps = 12
        st = self._stage([], duration=8.0, fps=fps)
        poses = [st.pose_at(i / fps, i)["Golu"] for i in range(2 * fps, 8 * fps)]  # long after any entry
        xs, dys, leans, tilts = ([p[k] for p in poses] for k in ("x", "dy", "lean", "tilt"))
        h = st.heights["Golu"]
        self.assertGreater(max(xs) - min(xs), h * 0.02)       # weight shift
        self.assertGreater(max(dys) - min(dys), h * 0.008)    # breathing
        self.assertGreater(max(leans) - min(leans), 2.0)      # body sway (degrees)
        self.assertGreater(max(tilts) - min(tilts), 3.0)      # head movement (degrees)
        # and it is visible in the pictures (camera is static here): two moments 1.3 s apart differ on the actor
        a, b = st.frame(3.0, 36), st.frame(4.3, 52)
        diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 30 else 0)
        self.assertGreater(sum(diff.histogram()[255:]), 500)

    async def test_speaking_gestures_and_listener_reaction(self):
        fps = 12
        st = self._stage([puppet.Talk("Golu", 1.0, 3.0, text="Chalo khelte hain?")], fps=fps, env=[0.6] * (6 * fps))
        sp = [st.pose_at(i / fps, i) for i in range(int(1.5 * fps), int(2.8 * fps))]
        idle = [st.pose_at(i / fps, i) for i in range(int(4.0 * fps), int(5.3 * fps))]
        self.assertGreater(sum(p["Golu"]["tilt"] for p in sp) / len(sp), sum(p["Golu"]["tilt"] for p in idle) / len(idle) + 3)  # '?' tilt
        self.assertGreater(sum(p["Golu"]["lean"] for p in sp) / len(sp), 1.0)       # leans toward the listener (right)
        self.assertLess(sum(p["Tortu"]["lean"] for p in sp) / len(sp), 0.0)         # listener turns toward the speaker


class _VoiceBase(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)

    async def asyncTearDown(self):
        await self.hub.jobs.stop(grace=1)
        self.hub.db.close()
        await super().asyncTearDown()

    async def _project(self):
        lib = self.hub.library
        pid = self.hub.projects.create_project("Dost", "2d")["id"]
        v = self.hub.scripts.create_version(pid, STORY)
        self.hub.scripts.approve(v["id"])
        await self.hub.storyboards.generate_draft(pid, use_ai=False)
        self.hub.storyboards.approve(pid)
        for role, shirt in (("Golu", (200, 60, 60)), ("Tortu", (60, 160, 60))):
            it = lib.create_item("character", role)
            lib.add_image(it["id"], "main", face_figure(shirt))
            lib.cast(pid, role, it["id"])
        e = lib.create_item("environment", "Jungle")
        lib.add_image(e["id"], "background", background())
        lib.cast(pid, "Jungle", e["id"])
        return pid

    async def _render_and_check(self, pid):
        job = anim_jobs.start(self.hub, pid, "preview")
        await self.hub.jobs.start()
        await self.hub.jobs.wait_idle(timeout=170)
        j = self.hub.jobs.get_job(job["id"])
        self.assertEqual(j["status"], "completed", j["error_message"])
        out = anim_jobs.exports(self.hub, pid)[0]
        meta = out["meta"]
        from app.exports.validate import check_av

        srt = (self.hub.settings.data_dir / meta["subtitles"]).read_text(encoding="utf-8")
        problems, m = await check_av(self.hub.settings, out["abs"], srt_text=srt)
        self.assertEqual(problems, [], m)
        self.assertGreater(m["max_volume"], -30)                     # clearly audible, not a silent track
        self.assertLess(abs(m["audio_seconds"] - m["video_seconds"]), 0.25)
        self.assertEqual(m["subtitles"], 3)
        stages = {s["stage_name"]: s for s in self.hub.jobs.stages(job["id"])}
        self.assertIn("voice_1", stages)
        return out, m


class VoiceRenderTests(_VoiceBase):
    @needs_ffmpeg
    async def test_render_with_voice_timeline_and_validation(self):
        self.hub.tts = FakeTTS()
        pid = await self._project()
        out, m = await self._render_and_check(pid)
        self.assertEqual(len(self.hub.tts.calls), 3)  # every line voiced (2 characters + narrator)
        from app.audio import tts as T

        vm = T.voice_map(self.hub.db, pid)
        self.assertEqual(set(vm), {"Golu", "Tortu"})
        self.assertNotEqual(vm["Golu"], vm["Tortu"])  # different voice styles

    @needs_ffmpeg
    async def test_silent_audio_is_caught(self):
        from app.exports.validate import check_av

        vid = self.tmp / "silent.mp4"
        import subprocess

        from app.observability.diagnostics import find_ffmpeg

        ff = find_ffmpeg(self.hub.settings)
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=12:d=2",
                        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", str(vid)], check=True)
        problems, _ = await check_av(self.hub.settings, vid, expected_seconds=5.0, srt_text="1\n00:00:01,000 --> 00:00:09,000\nhi\n")
        text = " ".join(problems)
        self.assertIn("khaali", text)        # silent
        self.assertIn("alag", text)          # audio 3 s vs video 2 s
        self.assertIn("timeline", text)      # 2 s vs planned 5 s
        self.assertIn("subtitles", text)     # subtitle past the end

    async def test_missing_voice_gives_clear_error(self):
        from app.core.errors import HubError

        self.hub.tts.voices_dir = self.tmp / "no-voices"
        with self.assertRaises(HubError) as cm:
            self.hub.tts.check("hindi")
        self.assertIn("piper", cm.exception.user_message.lower())


@unittest.skipUnless(real_piper_dir(), "real Piper voice not available (set UWB_PIPER_VOICES)")
class RealPiperTests(_VoiceBase):
    """Same representative project, real local Hindi voice (hi_IN-pratham-medium)."""

    async def test_real_hindi_voice_render(self):
        from app.audio.tts import PiperTTS

        self.hub.tts = PiperTTS(real_piper_dir())
        pid = await self._project()
        out, m = await self._render_and_check(pid)
        self.assertEqual(out["meta"]["voice"], "hi_IN-pratham-medium")
