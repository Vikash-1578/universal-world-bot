"""Evidence model shared by Research and Accuracy.

A claim is only as good as its QUOTES. A quote counts only if it appears verbatim (after whitespace/case/punctuation
normalisation) in the fetched page text — this is checked by code, so the AI cannot invent proof."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.web import domain_of, tier_of


def norm(s: str) -> str:
    return re.sub(r"[\W_]+", " ", (s or "").lower(), flags=re.U).strip()


def quote_in(quote: str, text: str) -> bool:
    q = norm(quote)
    return 20 <= len(q) <= 400 and q in norm(text)


_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
STOP = {"about", "what", "with", "from", "that", "this", "their", "there", "where", "which", "when", "have", "were", "real",
        "truth", "story", "mystery", "mysteries", "topic", "video", "facts", "behind", "hidden"}


def split_sentences(text: str, lo: int = 40, hi: int = 400) -> list[str]:
    """Page text -> unique, readable sentences (these are the ONLY things ever used as quotes)."""
    out, seen = [], set()
    for para in re.split(r"\n+", text or ""):
        for sent in _SPLIT.split(para.strip()):
            sent = " ".join(sent.split())
            k = norm(sent)
            if lo <= len(sent) <= hi and k not in seen:
                seen.add(k)
                out.append(sent)
    return out


def key_terms(text: str) -> list[str]:
    ws = [w for w in norm(text).split() if (len(w) > 3 or w.isdigit()) and w not in STOP]
    return list(dict.fromkeys(ws))[:8]


def relevant(text: str, terms: list[str], min_frac: float = 0.6) -> bool:
    """Does the page really talk about the topic? (5-letter prefixes, so 'mysteries' matches 'mystery')."""
    if not terms:
        return True
    pre = {w[:5] for w in norm(text).split()}
    return sum(1 for t in terms if t[:5] in pre) / len(terms) >= min_frac


def best_sentence(claim: str, sentences: list[str]) -> str | None:
    """Deterministic retrieval: the sentence that shares the most key words (and numbers) with the claim."""
    ct = set(key_terms(claim)) | {w for w in norm(claim).split() if w.isdigit()}
    if len(ct) < 2:
        return None
    best, score = None, 0.0
    for s in sentences:
        st = set(norm(s).split())
        hit = sum(1 for t in ct if t in st)
        if hit >= 2 and hit / len(ct) > score:
            best, score = s, hit / len(ct)
    return best if score >= 0.45 else None


@dataclass
class Source:
    id: str
    url: str
    title: str
    domain: str
    tier: str


@dataclass
class Claim:
    id: str
    text: str
    origin: str                                              # source id it was first extracted from
    support: dict[str, str] = field(default_factory=dict)   # source id -> verified quote
    contradict: dict[str, str] = field(default_factory=dict)
    status: str = "pending"                                  # pending | accepted | disputed | dropped
    note: str = ""


class EvidenceStore:
    """Source texts live on disk (agents/sources/<id>.txt); only small metadata goes into job checkpoints."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.sources: dict[str, Source] = {}
        meta = folder / "sources.json"
        if meta.exists():
            for d in json.loads(meta.read_text(encoding="utf-8")):
                self.sources[d["id"]] = Source(**d)

    def add(self, url: str, title: str, text: str) -> Source:
        sid = "s" + hashlib.sha256(url.encode()).hexdigest()[:8]
        if sid not in self.sources:
            dom = domain_of(url)
            self.sources[sid] = Source(sid, url, title[:150], dom, tier_of(dom))
            (self.folder / f"{sid}.txt").write_text(text[:60_000], encoding="utf-8")
            self._flush()
        return self.sources[sid]

    def text(self, sid: str) -> str:
        p = self.folder / f"{sid}.txt"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def has_url(self, url: str) -> bool:
        return any(s.url == url for s in self.sources.values())

    def _flush(self) -> None:
        (self.folder / "sources.json").write_text(json.dumps([s.__dict__ for s in self.sources.values()], ensure_ascii=False, indent=1),
                                                  encoding="utf-8")


def independent_domains(store: EvidenceStore, claim: Claim) -> set[str]:
    return {store.sources[s].domain for s in claim.support if s in store.sources}
