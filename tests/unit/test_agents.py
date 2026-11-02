"""Agents. The AI and the web are TEST DOUBLES: they prove our logic (proof must be a verbatim quote, 2 independent
domains, unproven claims dropped) — not that a real model or the real internet behaves this way."""
import json

from app.agents.accuracy import script_flags
from app.agents.evidence import quote_in
from app.agents.web import clean_links, domain_of, html_to_text, parse_ddg, safe_url, tier_of
from tests.helpers import TempDirCase, make_hub

BERMUDA = ("The Bermuda Triangle is a loosely defined region in the western part of the North Atlantic Ocean. "
           "Flight 19 was a group of five US Navy torpedo bombers that disappeared on 5 December 1945 during a training flight. "
           "The Coast Guard says it does not recognize the Bermuda Triangle as an official name. "
           "Lloyd's of London does not charge higher insurance rates for ships crossing the region. "
           "The area is often said to cover about 500,000 square miles, although estimates vary widely. ") * 2
PAGES = {
    "https://en.wikipedia.org/wiki/Bermuda_Triangle": ("Bermuda Triangle - Wikipedia", BERMUDA),
    "https://www.britannica.com/place/Bermuda-Triangle": ("Bermuda Triangle | Britannica", BERMUDA),
    "https://example-blog.com/bermuda": ("Blog", "A blog says aliens abduct ships in the triangle every single year without exception, sources unknown. " * 12),
}
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


QUOTES = {
    "loosely defined region": "The Bermuda Triangle is a loosely defined region in the western part of the North Atlantic Ocean.",
    "Flight 19": "Flight 19 was a group of five US Navy torpedo bombers that disappeared on 5 December 1945 during a training flight.",
    "Coast Guard": "The Coast Guard says it does not recognize the Bermuda Triangle as an official name.",
    "Lloyd": "Lloyd's of London does not charge higher insurance rates for ships crossing the region.",
    "square miles": "The area is often said to cover about 500,000 square miles, although estimates vary widely.",
}


class SmartLLM:
    """Answers by prompt type, like a model that is honest about what is on the page."""
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
            return {"queries": ["bermuda triangle"]}
        text = prompt.split("TEXT:", 1)[1]
        if "CLAIMS:" in prompt:  # accuracy cross-check
            claims = prompt.split("CLAIMS:", 1)[1].split("TEXT:", 1)[0]
            res = []
            for line in claims.strip().splitlines():
                n, claim = line.split(". ", 1)
                for key, quote in QUOTES.items():
                    if key in claim and quote in text:
                        res.append({"n": int(n), "verdict": "supports", "quote": quote})
                if "aliens" in claim:  # model claims support but invents a quote -> must be rejected by code
                    res.append({"n": int(n), "verdict": "supports", "quote": "Scientists confirmed that aliens abduct ships every year."})
            return {"results": res}
        if "aliens abduct" in text:  # extraction from the blog
            return {"claims": [{"claim": "Aliens abduct ships in the triangle every year", "quote": "A blog says aliens abduct ships in the triangle every single year without exception, sources unknown."}]}
        claims = [
            {"claim": "Bermuda Triangle is a loosely defined region of the North Atlantic", "quote": "The Bermuda Triangle is a loosely defined region in the western part of the North Atlantic Ocean."},
            {"claim": "Flight 19 disappeared on 5 December 1945", "quote": "Flight 19 was a group of five US Navy torpedo bombers that disappeared on 5 December 1945 during a training flight."},
            {"claim": "The Coast Guard does not recognize the Bermuda Triangle as an official name", "quote": "The Coast Guard says it does not recognize the Bermuda Triangle as an official name."},
            {"claim": "Lloyd's of London charges no extra insurance for the region", "quote": "Lloyd's of London does not charge higher insurance rates for ships crossing the region."},
            {"claim": "The area is often said to cover about 500,000 square miles", "quote": QUOTES["square miles"]},
            {"claim": "Made up claim", "quote": "This sentence is not on the page at all, the model invented it."},
        ]
        return {"claims": claims}


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

    async def test_quote_must_really_be_on_the_page(self):
        self.assertTrue(quote_in("flight 19 was a group of five US Navy torpedo bombers", "Flight 19 was a group of five US Navy torpedo bombers!"))
        self.assertFalse(quote_in("Scientists confirmed that aliens abduct ships", BERMUDA))
        self.assertFalse(quote_in("too short", "too short"))

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
        self.assertNotIn("Made up claim", proof.split("# Dropped")[0])  # invented quote never became a claim
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
