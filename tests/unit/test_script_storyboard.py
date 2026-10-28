"""Milestone 4. The AI used here is a TEST DOUBLE (FakeLLM) — it proves our handling of AI output,
not that a real model writes good scripts."""
import json
import tempfile
import zipfile
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer

from app.core.errors import Conflict, InvalidInput
from app.models.llm import LLM, LLMUnavailable, extract_json, strip_thinking
from app.scripts import parser
from app.scripts.inputs import read_text_file
from tests.helpers import TempDirCase, make_hub

SCRIPT = """Title: Kachhua aur Khargosh 2.0

[Scene 1: Jungle ka race track, subah]
Narrator: Sab jaante hain kachhua race jeeta tha... par dusri race me kya hua!
Khargosh: (gusse me) Is baar main sota nahi, seedha jeetunga!
Sher: Theek hai! Ready, set, go!

[Scene 2: Nadi ke kinare, dopahar]
(Khargosh tezi se bhaagta hai)
Khargosh: (darr ke) Arre! Pul toot gaya!
Kachhua: Meri peeth par baith jao dost.

[Scene 3: Finish line, shaam]
Sher: Aaj dosti jeet gayi!
"""


class FakeLLM:
    """Test double for the AI engine."""

    def __init__(self, replies=None, ok=True):
        self.replies = list(replies or [])
        self.ok = ok
        self.last_provider = "fake:model"
        self.prompts = []

    async def available(self):
        return self.ok

    async def chat(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else SCRIPT

    async def chat_json(self, prompt, **kw):
        self.prompts.append(prompt)
        return json.loads(self.replies.pop(0))


class ParserTests(TempDirCase):
    async def test_parse_structure(self):
        ps = parser.parse(SCRIPT)
        self.assertEqual(ps.title, "Kachhua aur Khargosh 2.0")
        self.assertEqual(len(ps.scenes), 3)
        self.assertEqual(ps.scenes[0].heading, "Jungle ka race track, subah")
        self.assertEqual(ps.characters, ["Khargosh", "Sher", "Kachhua"])
        l = ps.scenes[0].lines[1]
        self.assertEqual((l.kind, l.speaker, l.direction), ("dialogue", "Khargosh", "gusse me"))
        self.assertEqual(ps.scenes[0].lines[0].kind, "narration")
        self.assertEqual(ps.scenes[1].lines[0].kind, "action")
        self.assertGreater(ps.seconds, 10)
        again = parser.parse(parser.render(ps))
        self.assertEqual(again.to_dict(), ps.to_dict())  # round trip

    async def test_hindi_and_no_headers(self):
        ps = parser.parse("दृश्य 1: गाँव\nकथावाचक: एक गाँव था।\nराजू: नमस्ते!\n")
        self.assertEqual((ps.scenes[0].heading, ps.characters, ps.scenes[0].lines[0].kind), ("गाँव", ["राजू"], "narration"))
        plain = parser.parse("\n".join(f"Line number {i} of the story." for i in range(14)))
        self.assertEqual(len(plain.scenes), 3)
        self.assertTrue(all(l.kind == "narration" for s in plain.scenes for l in s.lines))
        self.assertEqual(parser.parse("Visit https://x.com: now").scenes[0].lines[0].kind, "narration")

    async def test_read_files(self):
        t = self.tmp
        (t / "a.txt").write_text(SCRIPT, encoding="utf-8")
        self.assertIn("Khargosh", read_text_file(t / "a.txt"))
        docx = t / "s.docx"
        body = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                '<w:p><w:r><w:t>Title: Doc</w:t></w:r></w:p><w:p><w:r><w:t>Raju: </w:t></w:r><w:r><w:t>Hello</w:t></w:r></w:p>'
                '</w:body></w:document>')
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("word/document.xml", body)
        self.assertEqual(read_text_file(docx), "Title: Doc\nRaju: Hello")
        (t / "e.txt").write_text("   ", encoding="utf-8")
        with self.assertRaises(InvalidInput):
            read_text_file(t / "e.txt")


class ScriptStoryboardTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.pid = self.hub.projects.create_project("Race", "2d")["id"]

    async def asyncTearDown(self):
        self.hub.db.close()
        await super().asyncTearDown()

    async def test_versions_and_approval_never_overwrite(self):
        sc = self.hub.scripts
        v1 = sc.create_version(self.pid, SCRIPT)
        sc.approve(v1["id"])
        v2 = sc.create_version(self.pid, SCRIPT.replace("dosti", "pyaar"))
        self.assertEqual(sc.approved(self.pid)["id"], v1["id"])  # new draft does not replace approved
        self.assertEqual(sc.get(v1["id"])["content"], SCRIPT.strip())
        sc.approve(v2["id"])
        self.assertEqual(sc.get(v1["id"])["approval_status"], "superseded")
        with self.assertRaises(Conflict):
            sc.reject(v2["id"])
        self.assertEqual([v["version_number"] for v in sc.versions(self.pid)], [2, 1])
        with self.assertRaises(InvalidInput):
            sc.create_version(self.pid, "hi")

    async def test_storyboard_rules_draft_edit_reorder_approve(self):
        sb = self.hub.storyboards
        sb.llm = FakeLLM(ok=False)  # no AI: rules-only draft must still work
        with self.assertRaises(Conflict):
            await sb.generate_draft(self.pid)  # script not approved yet
        v = self.hub.scripts.create_version(self.pid, SCRIPT)
        self.hub.scripts.approve(v["id"])
        st = await sb.generate_draft(self.pid)
        self.assertEqual((st["status"], st["source"]), ("draft", "rules only"))
        scenes = sb.scenes(self.pid)
        self.assertEqual(len(scenes), 3)
        self.assertEqual(scenes[0]["camera"]["shot"], "wide")
        self.assertEqual(scenes[1]["camera"]["lighting"], "bright daylight")
        self.assertEqual(scenes[2]["camera"]["lighting"], "warm sunset")
        self.assertEqual(scenes[0]["camera"]["emotions"], {"Khargosh": "gusse me"})
        sb.approve(self.pid)
        self.assertTrue(sb.is_approved(self.pid))
        with self.assertRaises(Conflict):
            await sb.generate_draft(self.pid)  # approved storyboard is not silently replaced
        sb.update_scene(self.pid, scenes[1]["id"], {"shot": "close-up", "description": "Pul toot-ta hai"})
        self.assertEqual(sb.state(self.pid)["status"], "changed")
        self.assertFalse(sb.is_approved(self.pid))
        order = [s["id"] for s in sb.reorder_scene(self.pid, scenes[2]["id"], 1)]
        self.assertEqual(order, [scenes[2]["id"], scenes[0]["id"], scenes[1]["id"]])
        with self.assertRaises(InvalidInput):
            sb.update_scene(self.pid, scenes[0]["id"], {"shot": "drone-hack"})
        with self.assertRaises(InvalidInput):
            sb.update_scene(self.pid, scenes[0]["id"], {"dialogue_json": "x"})
        sb.approve(self.pid)
        self.assertEqual(self.hub.projects.get_project(self.pid)["status"], "production")
        # script changes after approval -> storyboard no longer counts as approved
        v2 = self.hub.scripts.create_version(self.pid, SCRIPT + "Narrator: The end.\n")
        self.hub.scripts.approve(v2["id"])
        self.assertFalse(sb.is_approved(self.pid))
        with self.assertRaises(Conflict):
            sb.approve(self.pid)

    async def test_ai_director_suggestions_validated(self):
        reply = json.dumps({"scenes": [
            {"n": 1, "environment": "Jungle track", "shot": "two-shot", "movement": "pan left", "transition": "dissolve",
             "lighting": "golden", "mood": "excited", "props": ["flag"], "sfx": ["whistle"], "emotions": {"Sher": "proud"}},
            {"n": 2, "shot": "HACKER", "movement": "???", "sfx": ["splash"]},
        ]})
        sb = self.hub.storyboards
        sb.llm = FakeLLM([reply])
        v = self.hub.scripts.create_version(self.pid, SCRIPT)
        self.hub.scripts.approve(v["id"])
        st = await sb.generate_draft(self.pid)
        self.assertIn("AI Director", st["source"])
        s = sb.scenes(self.pid)
        self.assertEqual((s[0]["camera"]["shot"], s[0]["camera"]["transition"], s[0]["environment_ref"]), ("two-shot", "dissolve", "Jungle track"))
        self.assertEqual(s[1]["camera"]["shot"], "two-shot")  # invalid AI value -> kept rules default
        self.assertEqual(s[1]["camera"]["sfx"], ["splash"])
        self.assertEqual(s[2]["camera"]["source"], "rules")  # AI gave nothing for scene 3
        self.assertEqual(s[0]["dialogue"][1]["text"], "Is baar main sota nahi, seedha jeetunga!")  # dialogue untouched

    async def test_ai_director_failure_keeps_rules_draft(self):
        class Broken(FakeLLM):
            async def chat_json(self, prompt, **kw):
                raise ValueError("garbage")

        sb = self.hub.storyboards
        sb.llm = Broken()
        v = self.hub.scripts.create_version(self.pid, SCRIPT)
        self.hub.scripts.approve(v["id"])
        st = await sb.generate_draft(self.pid)
        self.assertIn("fail", st["source"])
        self.assertEqual(len(sb.scenes(self.pid)), 3)

    async def test_ai_write_job(self):
        self.hub.scripts.llm = FakeLLM(["```\n" + SCRIPT + "```"])
        self.hub.llm = self.hub.scripts.llm
        j = self.hub.jobs.submit_job("script_write", self.pid, {"project_id": self.pid, "text": "race with twist"})
        await self.hub.jobs.wait_idle()
        row = self.hub.jobs.get_job(j["id"])
        self.assertEqual(row["status"], "completed", row["error_message"])
        latest = self.hub.scripts.latest(self.pid)
        self.assertTrue(latest["content"].startswith("Title:"))
        self.assertIn("race with twist", self.hub.scripts.llm.prompts[0])


class LLMTests(TempDirCase):
    async def test_cloud_gate_and_local_first(self):
        hits = {"local": 0, "cloud": 0}

        async def tags(req):
            return web.json_response({"models": [{"name": "llama3.1:8b"}]})

        async def chat(req):
            body = await req.json()
            hits["local" if "Authorization" not in req.headers else "cloud"] += 1
            return web.json_response({"choices": [{"message": {"content": f"hi from {body['model']}"}}]})

        app = web.Application()
        app.router.add_get("/api/tags", tags)
        app.router.add_post("/v1/chat/completions", chat)
        srv = TestServer(app)
        await srv.start_server()
        url = f"http://{srv.host}:{srv.port}"
        try:
            cloud_on = {"v": False}
            llm = LLM([("groq", "gsk_x")], lambda: cloud_on["v"], ollama_url=url)
            self.assertEqual(await llm.chat("hello"), "hi from llama3.1:8b")
            self.assertEqual(hits, {"local": 1, "cloud": 0})
            # no local model + cloud OFF -> clear refusal, no network call to cloud
            llm2 = LLM([("groq", "gsk_x")], lambda: cloud_on["v"], ollama_url="http://127.0.0.1:9")
            with self.assertRaises(LLMUnavailable):
                await llm2.chat("hello")
            self.assertFalse(await llm2.available())
            cloud_on["v"] = True
            self.assertTrue(await llm2.available())
        finally:
            await srv.close()

    async def test_extract_json(self):
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('Sure! {"a": [1]} done'), {"a": [1]})
        self.assertIsNone(extract_json("no json"))

    async def test_strip_thinking(self):
        self.assertEqual(strip_thinking("<think>\nhmm plan\n</think>\n\nTitle: X"), "Title: X")
        self.assertEqual(strip_thinking("Title: Y <think>cut off"), "Title: Y")
