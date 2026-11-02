"""Agents. The AI and the web are TEST DOUBLES: they prove our logic (proof must be a verbatim quote, 2 independent
domains, unproven claims dropped) — not that a real model or the real internet behaves this way."""
import json

from app.agents.accuracy import script_flags
from app.agents.evidence import quote_in
from app.agents.web import clean_links, domain_of, html_to_text, parse_ddg, safe_url, tier_of
from tests.helpers import TempDirCase, make_hub

S_REGION = "The Bermuda Triangle is a loosely defined region in the western part of the North Atlantic Ocean."
S_FLIGHT = "Flight 19 was a group of five US Navy torpedo bombers that disappeared on 5 December 1945 during a training flight."
S_GUARD = "The Coast Guard says it does not recognize the Bermuda Triangle as an official name."
S_LLOYD = "Lloyd's of London does not charge higher insurance rates for ships crossing the region."
S_AREA = "The area is often said to cover about 500,000 square miles, although estimates vary widely."
FILLER = " ".join(f"Filler sentence number {i} about nothing in particular, written only to make this page long enough." for i in range(1, 9))
BERMUDA = " ".join([S_REGION, S_FLIGHT, S_GUARD, S_LLOYD, S_AREA]) + " " + FILLER.replace("nothing in particular", "ships and planes")
BLOG_S = "A blog about the Bermuda Triangle says aliens abduct ships every single year without exception, sources unknown."
PAGES = {
    "https://en.wikipedia.org/wiki/Bermuda_Triangle": ("Bermuda Triangle - Wikipedia", BERMUDA),
    "https://www.britannica.com/place/Bermuda-Triangle": ("Bermuda Triangle | Britannica", BERMUDA),
    "https://example-blog.com/bermuda": ("Blog", BLOG_S + " " + FILLER),
    "https://www.unrelated-shop.com/cats": ("Cats", " ".join(f"Cats are lovely pets and sleep sixteen hours a day, said veterinarian number {i} yesterday." for i in range(20))),
}
CLAIMS = {S_REGION: "The Bermuda Triangle is a loosely defined region of the North Atlantic",
          S_FLIGHT: "Flight 19 disappeared on 5 December 1945",
          S_GUARD: "The Coast Guard does not recognize the Bermuda Triangle as an official name",
          S_LLOYD: "Lloyd's of London charges no extra insurance for the region",
          S_AREA: "The area is often said to cover about 500,000 square miles",
          BLOG_S: "Aliens abduct ships in the Bermuda Triangle every year"}
GOOD = """Title: Bermuda Triangle ka raaz
[Scene 1: Hook]
(show: stormy ocean)
Narrator: Kya ek poora jahaz bina nishaan ke gayab ho sakta hai?
[Scene 2: Kahani]
(show: map of the Atlantic)
Narrator: Atlantic ke ek hisse ko log Bermuda Triangle kehte hain.
[Scene 3: Flight 19]
(show: old aircraft photo)
Narrator: Flight 19 ke paanch jahaz kho gaye the, par sach thoda alag hai.
[Scene 4: Science]
(show: ocean currents)
Narrator: Coast Guard is naam ko official nahi maanta.
[Scene 5: Result]
(show: sunset sea)
Narrator: Isliye rahasya kam, kahani zyada hai.
"""


class FakeWeb:
    def __init__(self, pages=PAGES):
        self.pages = pages
        self.searches = []

    async def search(self, q, limit=4):
        self.searches.append(q)
        return [{"url": u, "title": t} for u, (t, _) in self.pages.items()]

    async def fetch(self, url):
        t = self.pages.get(url)
        return {"url": url, "title": t[0], "text": t[1]} if t else None


class FakeBot:
    """Telegram test double: records the live progress message and its edits."""

    def __init__(self):
        self.sent, self.edits = [], []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent.append(text)
        return type("M", (), {"message_id": 7})()

    async def edit_message_text(self, text, chat_id=None, message_id=None, parse_mode=None):
        self.edits.append(text)

    async def send_document(self, *a, **k):
        pass


class SmartLLM:
    """Behaves like a sensible model: picks sentences, and judges pairs honestly."""
    ok = True
    last_provider = "fake:model"

    def __init__(self, script=GOOD, scripts=None):
        self.scripts = list(scripts or [script])
        self.prompts = []

    async def available(self):
        return True

    async def chat(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.scripts.pop(0) if len(self.scripts) > 1 else self.scripts[0]

    async def chat_json(self, prompt, **kw):
        self.prompts.append(prompt)
        if "search queries" in prompt:
            return {"queries": ["bermuda triangle", "bermuda triangle flight 19"]}
        if "PAIRS:" in prompt:
            res = []
            for line in prompt.split("PAIRS:", 1)[1].split("Return ONLY")[0].strip().splitlines():
                n, rest = line.split(". ", 1)
                claim, sent = rest.replace("CLAIM: ", "", 1).split(" || SENTENCE: ")
                same = CLAIMS.get(sent.strip()) == claim.strip()
                res.append({"n": int(n), "verdict": "supports" if same else "unrelated"})
            return {"results": res}
        res = [{"n": 99, "claim": "Out of range pick must be ignored"}]
        for line in prompt.split("SENTENCES from a web page:", 1)[1].split("Pick up to")[0].strip().splitlines():
            n, sent = line.split(". ", 1)
            if sent.strip() in CLAIMS:
                res.append({"n": int(n), "claim": CLAIMS[sent.strip()]})
        return {"claims": res}


class AgentTests(TempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.hub = make_hub(self.tmp)
        self.pid = self.hub.projects.create_project("Bermuda", "slideshow")["id"]

    async def asyncTearDown(self):
        await self.hub.jobs.stop(grace=1)
        self.hub.db.close()
        await super().asyncTearDown()

    def use(self, llm=None, web=None):
        self.hub.llm = self.hub.scripts.llm = llm or SmartLLM()
        self.hub.web = web or FakeWeb()

    async def run_job(self, topic="Bermuda Triangle ke raaz"):
        j = self.hub.jobs.submit_job("video_pipeline", self.pid, {"project_id": self.pid, "topic": topic})
        await self.hub.jobs.wait_idle(timeout=30)
        return self.hub.jobs.get_job(j["id"])

    # ---------------------------------------------------------------- helpers
    async def test_domains_tiers_and_url_safety(self):
        self.assertEqual(domain_of("https://hi.wikipedia.org/wiki/X"), domain_of("https://en.wikipedia.org/wiki/Y"))
        self.assertEqual(domain_of("https://www.bbc.co.uk/news"), "bbc.co.uk")
        self.assertEqual((tier_of("nasa.gov"), tier_of("isro.gov.in"), tier_of("wikipedia.org"), tier_of("myblog.com")), ("A", "A", "B", "C"))
        self.assertFalse(safe_url("http://127.0.0.1/admin") or safe_url("http://192.168.1.1/") or safe_url("file:///etc/passwd") or safe_url("http://localhost:8080"))
        self.assertTrue(safe_url("https://en.wikipedia.org/wiki/X"))
        title, text = html_to_text("<html><head><title>T</title><script>bad()</script></head><body><nav>menu</nav><p>Hello  world</p></body></html>")
        self.assertEqual((title, text), ("T", "Hello world"))

    async def test_parse_ddg_unwraps_redirects_and_blocks_private(self):
        html = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.nasa.gov%2Fx&amp;rut=abc">NASA <b>page</b></a>'
                '<a class="result__a" href="http://127.0.0.1/secret">bad</a>')
        self.assertEqual(parse_ddg(html), [{"url": "https://www.nasa.gov/x", "title": "NASA page"}])

    async def test_clean_links_unwraps_archive_and_keeps_one_per_domain(self):
        urls = ["https://web.archive.org/web/20200101000000/https://www.nasa.gov/a", "https://www.nasa.gov/b",
                "https://www.amazon.com/book", "https://en.wikipedia.org/wiki/X", "https://doi.org/10.1/x", "http://127.0.0.1/x",
                "https://www.bbc.com/news/1", "https://www.bbc.com/news/2", "https://x.edu/paper.pdf", "https://viaf.org/viaf/248502627", "https://d-nb.info/gnd/4005760-4"]
        self.assertEqual(clean_links(urls), ["https://www.nasa.gov/a", "https://www.bbc.com/news/1"])
        self.assertEqual(tier_of("archive.org"), "C")  # a web.archive.org snapshot must never count as a top source

    async def test_quote_and_sentence_tools(self):
        from app.agents.evidence import best_sentence, key_terms, relevant, split_sentences
        self.assertTrue(quote_in("flight 19 was a group of five US Navy torpedo bombers", S_FLIGHT))
        self.assertFalse(quote_in("Scientists confirmed that aliens abduct ships", BERMUDA))
        sents = split_sentences(BERMUDA)
        self.assertEqual(best_sentence("Flight 19 disappeared on 5 December 1945", sents), S_FLIGHT)
        self.assertIsNone(best_sentence("Napoleon lost at Waterloo in 1815", sents))
        self.assertTrue(relevant(BERMUDA, key_terms("bermuda triangle mysteries")))
        self.assertFalse(relevant(PAGES["https://www.unrelated-shop.com/cats"][1], key_terms("bermuda triangle")))

    async def test_two_blogs_agreeing_is_not_proof(self):
        from app.agents.accuracy import AccuracyAgent
        from app.agents.evidence import Claim, EvidenceStore
        store = EvidenceStore(self.tmp / "ev")
        a, b = store.add("https://one-blog.com/x", "a", "x"), store.add("https://two-blog.net/y", "b", "y")
        c = Claim("c1", "something", a.id, {a.id: "q" * 30, b.id: "q" * 30})
        AccuracyAgent.judge(store, c)
        self.assertEqual(c.status, "pending")  # two tier-C sites: not enough
        d = store.add("https://www.bbc.com/z", "c", "z")
        c.support[d.id] = "q" * 30
        AccuracyAgent.judge(store, c)
        self.assertEqual(c.status, "accepted")

    async def test_script_flags_unbacked_numbers_only_in_narration(self):
        text = "Title: T\n[Scene 1: A]\n(show: 1945 newsreel)\nNarrator: Flight 19 vanished in 1945 with 14 men.\n"
        self.assertEqual([f["numbers"] for f in script_flags(text, "Flight 19 vanished in 1945")], [["14"]])

    # ---------------------------------------------------------------- pipeline
    async def test_pipeline_keeps_only_proven_claims_and_writes_proof(self):
        llm = SmartLLM()
        self.use(llm)
        row = await self.run_job()
        self.assertEqual(row["status"], "completed", row["error_message"])
        out = json.loads(row["output_manifest"])
        self.assertTrue(out["passed"], out["report"])
        self.assertIsNone(self.hub.scripts.approved(self.pid))  # owner approves, never the agents
        folder = self.hub.projects.folder(self.pid, "agents")
        proof = (folder / "proof.md").read_text(encoding="utf-8")
        self.assertIn("Flight 19", proof)
        self.assertIn("britannica.com", proof)  # two independent domains for the same claim
        self.assertNotIn("Out of range", proof)  # a model pick that is not a real sentence is ignored
        self.assertNotIn("aliens", proof.split("# Dropped")[0])  # blog claim had a fake proof quote -> dropped
        script_prompt = [p for p in llm.prompts if "Use ONLY these checked facts" in p][0]
        self.assertIn("Flight 19 disappeared", script_prompt)
        self.assertNotIn("aliens", script_prompt)
        self.assertTrue((folder / "sources" / "sources.json").exists())

    async def test_single_weak_source_is_not_enough(self):
        only_wiki = {k: v for k, v in PAGES.items() if "wikipedia" in k}
        self.use(web=FakeWeb(only_wiki))
        row = await self.run_job()
        self.assertEqual(row["status"], "failed")  # 1 domain (tier B) cannot prove anything
        self.assertIn("Accuracy", row["error_message"])
        self.assertIsNone(self.hub.scripts.latest(self.pid))

    async def test_no_internet_fails_honestly(self):
        self.use(web=FakeWeb({}))
        row = await self.run_job()
        self.assertEqual(row["status"], "failed")
        self.assertIn("source nahi mila", row["error_message"])

    async def test_quality_failure_triggers_one_revision(self):
        bad = GOOD.replace("Title: Bermuda Triangle ka raaz\n", "")
        self.use(SmartLLM(scripts=[bad, GOOD]))
        row = await self.run_job()
        self.assertEqual(row["status"], "completed", row["error_message"])
        out = json.loads(row["output_manifest"])
        self.assertEqual((out["passed"], out["version"]), (True, 2))
        self.assertIn("Auto-badlaav: 1", out["report"])

    async def test_live_progress_message_is_edited_not_spammed(self):
        self.use()
        self.hub.bot = bot = FakeBot()
        j = self.hub.jobs.submit_job("video_pipeline", self.pid, {"project_id": self.pid, "topic": "Bermuda Triangle ke raaz"}, chat_id=5)
        await self.hub.jobs.wait_idle(timeout=30)
        self.assertEqual(self.hub.jobs.get_job(j["id"])["status"], "completed")
        self.assertIn("Research", bot.sent[0])
        self.assertEqual(len([m for m in bot.sent if m.startswith("🎬")]), 1)  # ONE live message, many edits
        last = bot.edits[-1]
        self.assertIn("100%", last)
        self.assertEqual(len([l for l in last.splitlines() if l.startswith("✅")]), 4, last)

    async def test_live_message_shows_where_it_failed(self):
        self.use(web=FakeWeb({}))
        self.hub.bot = bot = FakeBot()
        self.hub.jobs.submit_job("video_pipeline", self.pid, {"project_id": self.pid, "topic": "Bermuda Triangle ke raaz"}, chat_id=5)
        await self.hub.jobs.wait_idle(timeout=30)
        self.assertIn("❌ 🔎 Research", bot.edits[-1])
