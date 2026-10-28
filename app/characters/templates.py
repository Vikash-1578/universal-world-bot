"""Read-only template catalog: 48 hand-made + 1056 generated characters, and 97 places.
A template is only a text profile. "Use template" creates a real library item the owner then gives images to."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "catalog_files" / "catalog.json"
EXTRA_CATS = {
    "ghar": "🏠 Ghar-parivaar", "shahar": "🏙 Shahar", "professions": "👷 Kaam-dhande", "dharmik": "🛕 Dharmik",
    "keede": "🐞 Keede", "samundar": "🐠 Samundar", "fantasy": "🧚 Fantasy", "sabzi-phal": "🥕 Sabzi-Phal",
    "cheezein": "🧸 Cheezein", "ped-paudhe": "🌳 Ped-Paudhe", "jagah": "🏞 Jagah",
}


@lru_cache(maxsize=1)
def catalog() -> dict:
    from app.characters import catalog_gen

    base = json.loads(DATA.read_text(encoding="utf-8"))
    cats = {**base["categories"], **EXTRA_CATS}
    items = [{**c, "kind": "actor", "size": c.get("size", "medium"), "keywords": c.get("keywords", "")} for c in base["characters"]]
    seen = {c["id"] for c in items}
    for g in catalog_gen.build():
        if g["id"] not in seen:
            seen.add(g["id"])
            items.append(g)
    return {"style": base.get("style", ""), "categories": cats, "items": items}


def categories(kind: str = "actor") -> list[tuple[str, str, int]]:
    c = catalog()
    counts: dict[str, int] = {}
    for it in c["items"]:
        if it["kind"] == kind:
            counts[it["category"]] = counts.get(it["category"], 0) + 1
    return [(k, c["categories"].get(k, k), n) for k, n in counts.items()]


def entries(category: str | None = None, kind: str | None = None) -> list[dict]:
    return [it for it in catalog()["items"] if (category is None or it["category"] == category) and (kind is None or it["kind"] == kind)]


def get(template_id: str) -> dict | None:
    return next((it for it in catalog()["items"] if it["id"] == template_id), None)


HINDI = {  # common story words -> English keywords used in the catalog (Hindi names in scripts still find templates)
    "खरगोश": "rabbit khargosh", "कछुआ": "tortoise kachhua turtle", "कछूआ": "tortoise kachhua turtle", "शेर": "lion sher",
    "लोमड़ी": "fox lomdi", "बिल्ली": "cat billi", "कुत्ता": "dog kutta", "चिड़िया": "bird sparrow chidiya", "बुलबुल": "bird bulbul",
    "हाथी": "elephant hathi", "बंदर": "monkey bandar", "भालू": "bear bhalu", "हिरण": "deer hiran", "मोर": "peacock mor",
    "तोता": "parrot tota", "कौआ": "crow kauwa", "उल्लू": "owl ullu", "गाय": "cow gaay", "बकरी": "goat bakri", "चूहा": "mouse rat chuha",
    "मछली": "fish machli", "मेंढक": "frog mendhak", "सांप": "snake saanp", "साँप": "snake saanp", "बाघ": "tiger bagh", "घोड़ा": "horse ghoda",
    "दादा": "grandfather dada old", "दादी": "grandmother dadi old", "नाना": "grandfather nana old", "नानी": "grandmother nani old",
    "माँ": "mother maa", "पापा": "father papa", "राजा": "king raja", "रानी": "queen rani", "किसान": "farmer kisan",
    "डॉक्टर": "doctor", "टीचर": "teacher", "बच्चा": "child boy", "लड़का": "boy", "लड़की": "girl",
    "जंगल": "jungle forest", "नदी": "river nadi", "किनारा": "river bank", "गाँव": "village gaon", "गांव": "village gaon",
    "खेत": "farm field khet", "बगीचा": "garden bagicha", "बागान": "garden", "स्कूल": "school", "घर": "house home ghar",
    "बाज़ार": "market bazaar", "बाजार": "market bazaar", "पहाड़": "mountain pahad", "समुंदर": "sea beach", "महल": "palace mahal",
    "मंदिर": "temple mandir", "पेड़": "tree", "रास्ता": "road path", "शहर": "city shahar",
}


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^\w]+", (s or "").lower()) if len(t) > 1}


def search(query: str, kind: str | None = None, limit: int = 10) -> list[dict]:
    q = _tokens(query)
    for word, extra in HINDI.items():
        if word in (query or ""):
            q |= _tokens(extra)
    if not q:
        return []
    scored = []
    for it in catalog()["items"]:
        if kind and it["kind"] != kind:
            continue
        name = _tokens(it["name"]) | _tokens(it["id"].replace("_", " "))
        rest = _tokens(it.get("look", "")) | _tokens(it.get("keywords", "")) | _tokens(it["category"])
        score = 3 * len(q & name) + len(q & rest)
        if score:
            scored.append((score, it["id"], it))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [it for _, _, it in scored[:limit]]
