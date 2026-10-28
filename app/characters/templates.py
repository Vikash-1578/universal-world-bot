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


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^\w]+", (s or "").lower()) if len(t) > 1}


def search(query: str, kind: str | None = None, limit: int = 10) -> list[dict]:
    q = _tokens(query)
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
