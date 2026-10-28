"""Ready-made character library (our own characters, drawn once by AI and kept), plus casting helpers."""
from __future__ import annotations

import asyncio
import json
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image

from app.services import puppet
from app.utils.logging import get_logger

log = get_logger(__name__)
CATALOG_FILE = Path(__file__).resolve().parents[1] / "assets" / "character_catalog.json"


EXTRA_CATS = {
    "ghar": "🏠 Ghar-parivaar", "shahar": "🏙 Shahar", "professions": "👷 Kaam-dhande", "dharmik": "🛕 Dharmik",
    "keede": "🐞 Keede-makode", "samundar": "🐠 Samundar", "fantasy": "🧚 Fantasy", "sabzi-phal": "🥕 Sabzi-Phal",
    "cheezein": "🧸 Cheezein", "ped-paudhe": "🌳 Ped-Paudhe", "jagah": "🏞 Jagah (background)",
}


@lru_cache(maxsize=1)
def catalog() -> dict:
    from app.services import catalog_gen

    base = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    for e in base["characters"]:
        e.setdefault("kind", "actor")
        e.setdefault("tune", [0, 0])
        e.setdefault("size", "small" if e["age"] == "child" or e["id"] in ("chuha", "khargosh", "tota", "chidiya", "billi") else
                     "big" if e["id"] in ("sher", "hathi") else "medium")
        e.setdefault("keywords", "")
    base["categories"] = {**base["categories"], **EXTRA_CATS}
    base["characters"] = base["characters"] + catalog_gen.build()
    return base


def entries(category: str | None = None, kind: str | None = None) -> list[dict]:
    return [e for e in catalog()["characters"] if category in (None, "", e["category"]) and kind in (None, e.get("kind", "actor"))]


def categories() -> dict[str, str]:
    return catalog()["categories"]


def entry(eid: str) -> dict | None:
    return next((e for e in catalog()["characters"] if e["id"] == eid), None)


def lib_style() -> str:
    return catalog()["style"]


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z\u0900-\u097f]{3,}", (text or "").lower())}


def score(e: dict, text: str, gender: str | None = None, age: str | None = None) -> float:
    q = _tokens(text)
    if not q:
        return 0.0
    hay = _tokens(f"{e['name']} {e['look']} {e.get('keywords', '')} {e['category']}")
    sc = float(len(q & hay))
    if sc and gender and e.get("gender") == gender:
        sc += 0.5
    if sc and age and e.get("age") == age:
        sc += 0.5
    return sc


def search(text: str, kind: str | None = "actor", limit: int = 12, gender: str | None = None, age: str | None = None) -> list[dict]:
    scored = [(score(e, text, gender, age), e) for e in entries(None, kind)]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:limit]]


def bg_path(eid: str, size: str) -> Path:
    from app.services.story import character_dir

    return character_dir().parent / "backgrounds" / f"{eid}_{size}.jpg"


async def ensure_place(eid: str, deps, size: str = "landscape") -> Path | None:
    """Library background picture (drawn once per size, then reused by every story)."""
    from app.services.story import BG_PROMPT

    e = entry(eid)
    if e is None:
        return None
    p = bg_path(eid, size)
    if p.exists():
        return p
    try:
        data = await deps.images.generate(BG_PROMPT.format(style=lib_style(), place=e["look"])[:500], seed=11, size=size,
                                          enhance=False, no_text=True)
    except Exception as ex:  # noqa: BLE001
        log.warning("place_gen_failed id=%s err=%s", eid, type(ex).__name__)
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if getattr(deps, "usage", None) is not None:
        deps.usage.add("images")
    return p


def best_place(text: str) -> str | None:
    hits = [(score(e, text), e) for e in entries("jagah", "place")]
    hits = [h for h in hits if h[0] >= 2]
    if not hits:
        return None
    hits.sort(key=lambda h: -h[0])
    want_night = "night" in (text or "").lower() or "raat" in (text or "").lower()
    for _, e in hits:
        if e["id"].endswith("_raat") == want_night:
            return e["id"]
    return hits[0][1]["id"]


def key(eid: str) -> str:
    return f"lib_{eid}"


def path(eid: str) -> Path:
    from app.services.story import character_dir

    return character_dir() / f"{key(eid)}.png"


def is_ready(eid: str) -> bool:
    return path(eid).exists()


async def ensure(eid: str, deps, seed: int = 7, force: bool = False) -> tuple[Image.Image | None, bytes | None, Path | None]:
    """Library character picture: from disk, or drawn now (green screen -> cut-out) and saved for ever."""
    from app.services.story import SPRITE_PROMPT, save_character

    e = entry(eid)
    if e is None or e.get("kind") == "place":
        return None, None, None
    p = path(eid)
    raw_p = p.parent / f"{p.stem}__raw.img"
    if p.exists() and not force:
        try:
            return Image.open(p).convert("RGBA"), (raw_p.read_bytes() if raw_p.exists() else None), p
        except Exception:  # noqa: BLE001
            pass
    prompt = SPRITE_PROMPT.format(style=lib_style(), name=e["name"], look=e["look"])[:500]
    for k in range(3):
        try:
            data = await deps.images.generate(prompt, seed=seed + 97 * k, size="portrait", enhance=False, no_text=True)
        except Exception as ex:  # noqa: BLE001
            log.warning("library_gen_failed id=%s err=%s", eid, type(ex).__name__)
            await asyncio.sleep(2)
            continue
        if getattr(deps, "usage", None) is not None:
            deps.usage.add("images")
        img = await asyncio.to_thread(puppet.key_sprite, data)
        if img is not None:
            if force:
                for old in p.parent.glob(p.stem + "__f_*.png"):
                    old.unlink(missing_ok=True)
            save_character(key(eid), img, data, {"name": e["name"], "look": e["look"], "style": lib_style(),
                                                 "voice": e["voice"], "category": e["category"], "library": eid})
            return img, data, p
    return None, None, None


# ---------------------------------------------------------------- casting
WORDS = {
    "sher": ["lion", "sher", "शेर", "raja of jungle"], "chuha": ["mouse", "chuha", "chuhiya", "चूह"], "bandar": ["monkey", "bandar", "बंदर"],
    "hathi": ["elephant", "hathi", "हाथी"], "lomdi": ["fox", "lomdi", "लोमड़ी"], "khargosh": ["rabbit", "khargosh", "खरगोश"],
    "kachua": ["tortoise", "turtle", "kachua", "कछुआ"], "kutta": ["dog", "kutta", "कुत्ता"], "billi": ["cat", "billi", "बिल्ली"],
    "tota": ["parrot", "tota", "तोता"], "kauwa": ["crow", "kauwa", "कौआ"], "chidiya": ["sparrow", "chidiya", "चिड़िया"],
    "mor": ["peacock", "mor", "मोर"], "ullu": ["owl", "ullu", "उल्लू"], "bhoot": ["ghost", "bhoot", "भूत"], "chudail": ["witch", "chudail", "चुड़ैल"],
    "kankal": ["skeleton", "कंकाल"], "tantrik": ["tantrik", "तांत्रिक"], "raja": ["king", "raja", "राजा"], "rani": ["queen", "rani", "रानी"],
    "rishi": ["sage", "rishi", "muni", "ऋषि", "मुनि"], "sainik": ["soldier", "sainik", "सैनिक"], "mantri": ["minister", "mantri", "मंत्री"],
    "doctor": ["doctor", "डॉक्टर"], "police": ["police", "inspector", "पुलिस"], "teacher_f": ["teacher", "madam", "मैडम"],
    "teacher_m": ["masterji", "sir", "मास्टर"], "boss": ["boss", "बॉस"], "dukandar": ["shopkeeper", "lala", "दुकानदार"],
    "thelewala": ["vendor", "thela", "ठेला"], "mukhiya": ["mukhiya", "headman", "sarpanch", "मुखिया"], "kisan_ramu": ["farmer", "kisan", "किसान"],
    "dada_gaon": ["grandfather", "dadaji", "दादा"], "dadi_gaon": ["grandmother", "dadi", "दादी", "नानी"], "baby": ["baby", "toddler", "मुन्ना"],
}


def heuristic(name: str, look: str, gender: str = "m", age: str = "adult", used: set[str] | None = None) -> str | None:
    used = used or set()
    text = f"{name} {look}".lower()
    for eid, ws in WORDS.items():
        if eid not in used and any(w.lower() in text for w in ws):
            return eid
    if any(w in text for w in ("mother", "maa", "माँ", "mummy")):
        return "maa_shahar" if "maa_shahar" not in used else "kisan_patni"
    if any(w in text for w in ("father", "papa", "पापा", "पिता")):
        return "papa_shahar" if "papa_shahar" not in used else "kisan_ramu"
    found = [e["id"] for e in search(f"{name} {look}", "actor", 5, gender, age) if e["id"] not in used]
    if found:
        return found[0]
    if age == "child":
        pool = ["bacha_raju", "bacha_golu", "student_boy"] if gender == "m" else ["bachi_priya", "student_girl", "billi"]
    elif age == "old":
        pool = ["dada_gaon", "teacher_m", "rishi"] if gender == "m" else ["dadi_gaon"]
    else:
        pool = ["kisan_ramu", "papa_shahar", "employee_m", "dukandar"] if gender == "m" else ["kisan_patni", "maa_shahar", "employee_f", "teacher_f"]
    return next((x for x in pool if x not in used), None)


def catalog_for_llm() -> str:
    return "\n".join(f"{e['id']}: {e['name']} ({e['category']}, {e['gender']}, {e['age']}) - {e['look'][:70]}"
                     for e in catalog()["characters"][:48])


async def match_cast(st, llm=None) -> dict[str, str]:
    """character id -> library id (best looking match, each library character used once)."""
    out: dict[str, str] = {}
    if llm is not None and st.characters:
        chars = "\n".join(f"{c.id}: {c.name} ({c.gender}, {c.age}) - {c.look[:100]}" for c in st.characters)
        short: dict[str, dict] = {}
        for c in st.characters:
            for e in search(f"{c.name} {c.look}", "actor", 10, c.gender, c.age):
                short[e["id"]] = e
        lib_text = "\n".join(f"{e['id']}: {e['name']} ({e['category']}, {e['gender']}, {e['age']}) - {e['look'][:70]}"
                             for e in list(short.values())[:60]) or catalog_for_llm()
        prompt = ("Match each story character to the most suitable ready-made cartoon character from the library "
                  "(same kind of being, gender and age; animals to animals). Use each library id at most once; use null if nothing fits.\n"
                  f"STORY CHARACTERS:\n{chars}\n\nLIBRARY:\n{lib_text}\n\n"
                  'Return ONLY JSON like {"story_id": "library_id or null"}')
        try:
            m = re.search(r"\{.*\}", await llm(prompt), re.S)
            data = json.loads(m.group(0)) if m else {}
            ids = {e["id"] for e in entries()}
            for c in st.characters:
                v = data.get(c.id)
                if isinstance(v, str) and v in ids and v not in out.values():
                    out[c.id] = v
        except Exception as e:  # noqa: BLE001
            log.warning("match_cast_llm_failed err=%s", type(e).__name__)
    for c in st.characters:
        if c.id not in out:
            g = heuristic(c.name, c.look, c.gender, c.age, set(out.values()))
            if g:
                out[c.id] = g
    return out


def apply_cast(st, cast_map: dict[str, str]) -> None:
    """Use the library character's look and size for the story character."""
    for c in st.characters:
        e = entry(cast_map.get(c.id, ""))
        if e:
            c.look = e["look"]
            c.size = e.get("size", c.size)
            st.voices[c.id] = voice_for(e, st.language)
            if e.get("tune") and any(e["tune"]):
                st.tune[c.id] = (int(e["tune"][0]), int(e["tune"][1]))
    st.cast_map = dict(cast_map)


def voice_for(e: dict, language: str = "hindi") -> str:
    v = e.get("voice", "hi-man")
    if language != "hindi" and v.startswith("hi-"):
        v = "en-" + v[3:]
    if language == "hindi" and v.startswith("en-"):
        v = "hi-" + v[3:]
    return v


def next_in(category: str, current: str | None, step: int = 1) -> str:
    ids = [e["id"] for e in entries(category)]
    if not ids:
        return current or ""
    if current not in ids:
        return ids[0]
    return ids[(ids.index(current) + step) % len(ids)]
