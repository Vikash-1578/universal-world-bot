"""Accuracy agent: nothing moves on unless it is PROVEN.

A claim is accepted only when
  * at least 2 independent domains each back it with a verbatim quote (code-checked), or
  * 1 top-tier source (.gov / .edu / major institution) backs it, and
  * no source contradicts it.
Unproven claims go back to Research for targeted searches (max 2 rounds). Whatever is still unproven is DROPPED.
This is the strongest check a laptop can do — it is not a guarantee of truth, so the owner still approves the script."""
from __future__ import annotations

import re
from dataclasses import asdict

from app.agents.base import Agent, AgentResult, Brief
from app.agents.evidence import Claim, EvidenceStore, best_sentence, independent_domains, key_terms, norm, quote_in, split_sentences
from app.agents.research import ResearchAgent
from app.scripts import parser

MIN_ACCEPTED = 5
ROUNDS = 2
PER_ROUND = 8
BATCH = 15
PAIR_PROMPT = """Decide for each pair whether the SENTENCE (from a web page) states the same fact as the CLAIM.
"supports" = the same fact, including the same numbers and dates. "contradicts" = a conflicting fact. Otherwise "unrelated". Be strict.

PAIRS:
{pairs}

Return ONLY JSON: {{"results": [{{"n": 1, "verdict": "supports|contradicts|unrelated"}}]}}"""
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUM.findall(text or "")}


def script_flags(script_text: str, allowed_text: str) -> list[dict]:
    """Narration sentences containing a number/year that no accepted claim contains (deterministic safety net)."""
    allowed = numbers_in(allowed_text)
    out = []
    for sc in parser.parse(script_text).scenes:
        for ln in sc.lines:
            if ln.kind == "action":  # (show: ...) hints are not claims
                continue
            extra = sorted(n for n in numbers_in(ln.text) if n not in allowed)
            if extra:
                out.append({"scene": sc.number, "text": ln.text[:160], "numbers": extra})
    return out


class AccuracyAgent(Agent):
    name = "accuracy"
    role = "Only proven claims pass"

    def __init__(self, hub, research: ResearchAgent | None = None) -> None:
        super().__init__(hub)
        self.research = research or ResearchAgent(hub)

    async def cross_check(self, store: EvidenceStore, claims: list[Claim], source_ids: list[str]) -> None:
        """For each page: pick, in code, the sentence closest to each claim; the model only says same-fact / conflict / unrelated.
        The proof quote is that sentence itself, so it is always really on the page."""
        for idx, sid in enumerate(source_ids, 1):
            await self.say(f"proof check — page {idx}/{len(source_ids)}")
            text = store.text(sid)
            sents = split_sentences(text)
            pairs = []
            for c in claims:
                if sid in c.support or sid in c.contradict:
                    continue
                s = best_sentence(c.text, sents)
                if s:
                    pairs.append((c, s))
            for i in range(0, len(pairs), BATCH):
                batch = pairs[i:i + BATCH]
                prompt = PAIR_PROMPT.format(pairs="\n".join(f"{n}. CLAIM: {c.text} || SENTENCE: {s}" for n, (c, s) in enumerate(batch, 1)))
                try:
                    raw = await self.hub.llm.chat_json(prompt, max_tokens=800)
                except Exception:  # noqa: BLE001 - an unreadable answer proves nothing
                    continue
                for r in (raw.get("results") if isinstance(raw, dict) else None) or []:
                    if not isinstance(r, dict) or not str(r.get("n", "")).isdigit() or not 1 <= int(r["n"]) <= len(batch):
                        continue
                    c, sent = batch[int(r["n"]) - 1]
                    if not quote_in(sent, text):
                        continue
                    if r.get("verdict") == "supports":
                        c.support[sid] = sent
                    elif r.get("verdict") == "contradicts":
                        c.contradict[sid] = sent

    @staticmethod
    def judge(store: EvidenceStore, c: Claim) -> None:
        if c.contradict:
            c.status, c.note = "disputed", "Kisi source ne iske ulta likha hai."
            return
        doms = independent_domains(store, c)
        tiers = [store.sources[s].tier for s in c.support if s in store.sources]
        top = "A" in tiers
        if len(doms) >= 2 and ("A" in tiers or "B" in tiers):  # two blogs agreeing with each other is not proof
            c.status, c.note = "accepted", f"{len(doms)} alag sites ne confirm kiya."
        elif top:
            c.status, c.note = "accepted", "Ek top-tier source (gov/edu/institution) ne confirm kiya."
        else:
            c.status = "pending"

    async def run(self, brief: Brief, store: EvidenceStore, claims_raw: list[dict]) -> AgentResult:
        claims = [Claim(**c) for c in claims_raw]
        await self.cross_check(store, claims, list(store.sources))
        for c in claims:
            self.judge(store, c)
        for _ in range(ROUNDS):
            todo = [c for c in claims if c.status == "pending"][:PER_ROUND]
            if not todo:
                break
            new_ids: list[str] = []
            await self.say(f"{len(todo)} claim ka proof nahi mila — dusri sites par dhundh raha hoon")
            for c in todo:  # targeted re-research: search for THIS claim on other domains
                have = independent_domains(store, c)
                for s in await self.research.gather([c.text[:140]], store, 2, skip_domains=have, terms=key_terms(c.text), min_frac=0.5):
                    new_ids.append(s.id)
            await self.cross_check(store, todo, list(dict.fromkeys(new_ids)))
            for c in todo:
                self.judge(store, c)
        for c in claims:
            if c.status == "pending":
                c.status, c.note = "dropped", "Proof nahi mila (kam se kam 2 alag sites chahiye)."
        acc = [c for c in claims if c.status == "accepted"]
        res = AgentResult(self.name, ok=len(acc) >= MIN_ACCEPTED, provider=self.hub.llm.last_provider, data={
            "accepted": [self._export(store, c) for c in acc],
            "disputed": [self._export(store, c) for c in claims if c.status == "disputed"],
            "dropped": [c.text for c in claims if c.status == "dropped"]})
        if not res.ok:
            doms = {x.domain for x in store.sources.values()}
            res.notes.append(f"Sirf {len(acc)} claim proof ke saath bache (minimum {MIN_ACCEPTED}). Mili: {len(store.sources)} pages, "
                             f"{len(doms)} alag site ({', '.join(sorted(doms)[:4])}).")
            if len(doms) < 2:
                res.notes.append("Proof ke liye 2 alag sites chahiye — internet/search check karo ya keys.txt me brave:<key> daalo.")
        self.save(brief.project_id, res)
        self.write_proof(brief.project_id, res.data)
        return res

    @staticmethod
    def _export(store: EvidenceStore, c: Claim) -> dict:
        ev = [{"url": store.sources[s].url, "title": store.sources[s].title, "tier": store.sources[s].tier, "quote": q}
              for s, q in c.support.items() if s in store.sources]
        return {"id": c.id, "text": c.text, "note": c.note, "evidence": ev,
                "against": [{"url": store.sources[s].url, "quote": q} for s, q in c.contradict.items() if s in store.sources]}

    def write_proof(self, pid: int, data: dict) -> None:
        lines = ["# Proof pack", ""]
        for c in data["accepted"]:
            lines += [f"## {c['text']}", f"_{c['note']}_", ""]
            lines += [f"- [{e['title'] or e['url']}]({e['url']}) (tier {e['tier']}): \"{e['quote']}\"" for e in c["evidence"]] + [""]
        if data["disputed"]:
            lines += ["# Disputed (NOT used)", ""] + [f"- {c['text']}" for c in data["disputed"]] + [""]
        if data["dropped"]:
            lines += ["# Dropped (no proof)", ""] + [f"- {t}" for t in data["dropped"]]
        (self.hub.projects.folder(pid, "agents") / "proof.md").write_text("\n".join(lines), encoding="utf-8")
