"""Research agent: topic -> real web pages -> claims, each with a VERBATIM quote from the page as proof.

The AI proposes queries and picks claims, but a claim is kept only if its quote really appears in the fetched page
(checked in code). Pages and quotes are stored under project/agents/sources, so the owner can open every proof."""
from __future__ import annotations

import asyncio
from dataclasses import asdict

from app.agents.base import Agent, AgentResult, Brief, clip
from app.agents.evidence import Claim, EvidenceStore, Source, norm, quote_in
from app.agents.web import domain_of
from app.core.errors import InvalidInput

MAX_SOURCES = 8
WIKI_SKIP_AFTER = 2  # at most this many Wikipedia pages: more of the same site adds no independent proof
MAX_CLAIMS = 30
QUERY_PROMPT = """Topic for a factual YouTube video: {topic}
Write 3-5 web search queries that would find reliable pages (encyclopedias, universities, museums, science/history sites).
Return ONLY JSON: {{"queries": ["..."]}}"""
EXTRACT_PROMPT = """TOPIC: {topic}

TEXT:
{text}

List up to 6 clear, specific factual claims from TEXT that matter for a video on the topic (names, dates, numbers, causes).
For each claim give "quote": ONE sentence copied EXACTLY, character for character, from TEXT (max 250 characters).
Return ONLY JSON: {{"claims": [{{"claim": "short statement", "quote": "exact sentence from TEXT"}}]}}"""


def passage(text: str, limit: int = 4500) -> str:
    return text[:limit]


class ResearchAgent(Agent):
    name = "research"
    role = "Web research with verbatim proof for every claim"

    async def _queries(self, brief: Brief) -> list[str]:
        try:
            d = await self.hub.llm.chat_json(QUERY_PROMPT.format(topic=brief.topic), max_tokens=300)
            qs = [clip(q, 120) for q in (d.get("queries") if isinstance(d, dict) else []) or [] if clip(q, 120)]
        except Exception:  # noqa: BLE001 - the topic itself is a fine query
            qs = []
        return (qs[:5] or []) + ([brief.topic[:120]] if brief.topic[:120] not in qs else [])

    async def gather(self, queries: list[str], store: EvidenceStore, limit: int, skip_domains: set[str] | None = None) -> list[Source]:
        """Search + fetch up to `limit` NEW pages. One page per URL; prefers different domains."""
        hits: list[dict] = []
        for res in await asyncio.gather(*(self.hub.web.search(q) for q in queries)):
            hits += res
        seen, picked = set(), []
        for h in hits:  # first pass: one hit per domain, then the rest
            d = domain_of(h["url"])
            if h["url"] in seen or store.has_url(h["url"]) or (skip_domains and d in skip_domains):
                continue
            seen.add(h["url"])
            picked.append(h)
        doms: set[str] = set()
        firsts = []
        rest = []
        for h in picked:
            d = domain_of(h["url"])
            (rest if d in doms else firsts).append(h)
            doms.add(d)
        order, wiki = [], 0
        for h in firsts + rest:
            if domain_of(h["url"]) == "wikipedia.org":
                wiki += 1
                if wiki > WIKI_SKIP_AFTER:
                    continue
            order.append(h)
        order = order[: limit * 2]
        pages = await asyncio.gather(*(self.hub.web.fetch(h["url"]) for h in order))
        out: list[Source] = []
        for h, p in zip(order, pages):
            if p and len(p["text"]) > 300 and len(out) < limit:
                out.append(store.add(p["url"], p["title"] or h["title"], p["text"]))
        return out

    async def run(self, brief: Brief, store: EvidenceStore) -> AgentResult:
        queries = await self._queries(brief)
        sources = await self.gather(queries, store, MAX_SOURCES)
        if not sources:
            raise InvalidInput("Internet/search se koi source nahi mila. Internet check karo (Wikipedia khulta hai?) "
                               "ya keys.txt me `brave:<key>` daalo.")
        claims: list[Claim] = []
        seen: set[str] = set()
        for src in sources:
            if len(claims) >= MAX_CLAIMS:
                break
            try:
                raw = await self.hub.llm.chat_json(EXTRACT_PROMPT.format(topic=brief.topic, text=passage(store.text(src.id))), max_tokens=1500)
            except Exception:  # noqa: BLE001 - one bad page must not stop the research
                continue
            for c in (raw.get("claims") if isinstance(raw, dict) else None) or []:
                if not isinstance(c, dict):
                    continue
                text, quote = clip(c.get("claim"), 300), clip(c.get("quote"), 400)
                if len(text) < 10 or norm(text) in seen or not quote_in(quote, store.text(src.id)):
                    continue  # quote not really on the page -> no proof -> discard
                seen.add(norm(text))
                claims.append(Claim(f"c{len(claims) + 1}", text, src.id, {src.id: quote}))
        res = AgentResult(self.name, ok=len(claims) >= 3, provider=self.hub.llm.last_provider,
                          data={"queries": queries, "sources": len(sources), "claims": [asdict(c) for c in claims]},
                          notes=[] if len(claims) >= 3 else ["Proof ke saath bahut kam claims mile."])
        self.save(brief.project_id, res)
        return res
