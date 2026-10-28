"""Free stock footage / photos: Pexels, Pixabay (free keys) and NASA, Wikimedia Commons, Internet Archive (no key)."""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import aiohttp

from app.utils.logging import get_logger

log = get_logger(__name__)

UA = {"User-Agent": "UniversalWorldBot/1.0 (personal Telegram bot)"}
PEXELS = "https://api.pexels.com"
PIXABAY = "https://pixabay.com/api"
NASA = "https://images-api.nasa.gov"
COMMONS = "https://commons.wikimedia.org/w/api.php"
ARCHIVE = "https://archive.org"
MAX_BYTES = 45 * 1024 * 1024
ALL_SOURCES = ("pexels", "pixabay", "nasa", "wikimedia", "archive")


@dataclass
class Cand:
    url: str
    kind: str  # video | image
    source: str
    credit: str
    page: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0


@dataclass
class StockClip:
    path: Path
    kind: str
    source: str
    credit: str
    page: str = ""


# ---------------------------------------------------------------- parsers (pure, unit tested)
def _score(w: int, h: int, portrait: bool, want_short: int = 720) -> float:
    if not w or not h:
        return 1e9
    short = min(w, h)
    pen = abs(short - want_short)
    if short < want_short:
        pen += 400  # too small looks blurry
    if (h > w) != portrait:
        pen += 150  # wrong orientation gets cropped hard
    return pen


def parse_pexels_videos(j: dict, portrait: bool) -> list[Cand]:
    out = []
    for v in j.get("videos", []) or []:
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("link")]
        if not files:
            continue
        f = min(files, key=lambda f: _score(f.get("width") or 0, f.get("height") or 0, portrait))
        out.append(Cand(f["link"], "video", "pexels", "Video: " + (v.get("user") or {}).get("name", "Pexels") + " / Pexels",
                        v.get("url", ""), f.get("width") or 0, f.get("height") or 0, float(v.get("duration") or 0)))
    return out


def parse_pixabay_videos(j: dict) -> list[Cand]:
    out = []
    for h in j.get("hits", []) or []:
        vs = h.get("videos") or {}
        v = vs.get("medium") or vs.get("small") or vs.get("large") or vs.get("tiny")
        if not v or not v.get("url"):
            continue
        out.append(Cand(v["url"], "video", "pixabay", f"Video: {h.get('user', 'Pixabay')} / Pixabay", h.get("pageURL", ""),
                        v.get("width") or 0, v.get("height") or 0, float(h.get("duration") or 0)))
    return out


def parse_pexels_photos(j: dict) -> list[Cand]:
    out = []
    for p in j.get("photos", []) or []:
        src = p.get("src") or {}
        u = src.get("large2x") or src.get("large") or src.get("original")
        if u:
            out.append(Cand(u, "image", "pexels", "Photo: " + p.get("photographer", "Pexels") + " / Pexels", p.get("url", ""),
                            p.get("width") or 0, p.get("height") or 0))
    return out


def parse_pixabay_images(j: dict) -> list[Cand]:
    out = []
    for h in j.get("hits", []) or []:
        u = h.get("largeImageURL") or h.get("webformatURL")
        if u:
            out.append(Cand(u, "image", "pixabay", f"Photo: {h.get('user', 'Pixabay')} / Pixabay", h.get("pageURL", ""),
                            h.get("imageWidth") or 0, h.get("imageHeight") or 0))
    return out


def nasa_pick(urls: list[str], kind: str) -> str | None:
    exts = (".mp4",) if kind == "video" else (".jpg", ".jpeg", ".png")
    cand = [u for u in urls if u.lower().endswith(exts)]
    for tag in ("~medium", "~mobile", "~large", "~small"):
        for u in cand:
            if tag in u:
                return u
    plain = [u for u in cand if "~orig" not in u and "~thumb" not in u]
    return plain[0] if plain else None


def parse_commons(j: dict, kind: str) -> list[Cand]:
    out = []
    for p in ((j.get("query") or {}).get("pages") or {}).values():
        info = (p.get("imageinfo") or [None])[0]
        if not info or not info.get("url"):
            continue
        mime = info.get("mime", "")
        if kind == "video" and not mime.startswith("video/"):
            continue
        if kind == "image" and not mime.startswith("image/"):
            continue
        if info.get("size", 0) > MAX_BYTES:
            continue
        meta = info.get("extmetadata") or {}
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "") or "Wikimedia Commons")[:60]
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        out.append(Cand(info["url"], kind, "wikimedia", f"{artist} ({lic}) / Wikimedia Commons".replace(" ()", ""),
                        info.get("descriptionurl", ""), info.get("width") or 0, info.get("height") or 0,
                        float(info.get("duration") or 0)))
    return out


def archive_pick(files: list[dict]) -> dict | None:
    ok = []
    for f in files:
        name = f.get("name", "")
        try:
            size = int(f.get("size") or 0)
        except ValueError:
            size = 0
        if name.lower().endswith(".mp4") and 0 < size <= MAX_BYTES:
            ok.append((size, f))
    return max(ok, key=lambda t: t[0])[1] if ok else None


# ---------------------------------------------------------------- service
class StockService:
    def __init__(self, pexels_key: str = "", pixabay_key: str = "", sources: str | None = None, timeout: float = 30.0) -> None:
        self._pexels = pexels_key.strip()
        self._pixabay = pixabay_key.strip()
        order = (sources or os.environ.get("STOCK_SOURCES") or ",".join(ALL_SOURCES)).split(",")
        self.sources = [s.strip().lower() for s in order if s.strip().lower() in ALL_SOURCES]
        self._timeout = timeout

    @classmethod
    def from_env(cls, env: dict | None = None) -> "StockService":
        e = env if env is not None else os.environ
        return cls(e.get("PEXELS_API_KEY", ""), e.get("PIXABAY_API_KEY", ""))

    def active_sources(self) -> list[str]:
        out = []
        for s in self.sources:
            if s == "pexels" and not self._pexels:
                continue
            if s == "pixabay" and not self._pixabay:
                continue
            out.append(s)
        return out

    @property
    def enabled(self) -> bool:
        return bool(self.active_sources())

    async def _get_json(self, s: aiohttp.ClientSession, url: str, **kw):
        async with s.get(url, **kw) as r:
            if r.status != 200:
                raise aiohttp.ClientError(f"http {r.status}")
            return await r.json(content_type=None)

    async def _candidates(self, s: aiohttp.ClientSession, source: str, q: str, portrait: bool, kind: str) -> list[Cand]:
        if source == "pexels":
            h = {"Authorization": self._pexels, **UA}
            if kind == "video":
                j = await self._get_json(s, f"{PEXELS}/videos/search", params={"query": q, "per_page": 8, "orientation": "portrait" if portrait else "landscape"}, headers=h)
                return parse_pexels_videos(j, portrait)
            j = await self._get_json(s, f"{PEXELS}/v1/search", params={"query": q, "per_page": 8, "orientation": "portrait" if portrait else "landscape"}, headers=h)
            return parse_pexels_photos(j)
        if source == "pixabay":
            if kind == "video":
                j = await self._get_json(s, f"{PIXABAY}/videos/", params={"key": self._pixabay, "q": q, "per_page": 8, "safesearch": "true"}, headers=UA)
                return parse_pixabay_videos(j)
            j = await self._get_json(s, f"{PIXABAY}/", params={"key": self._pixabay, "q": q, "per_page": 8, "image_type": "photo", "safesearch": "true",
                                                              "orientation": "vertical" if portrait else "horizontal"}, headers=UA)
            return parse_pixabay_images(j)
        if source == "nasa":
            j = await self._get_json(s, f"{NASA}/search", params={"q": q, "media_type": kind, "page_size": 6}, headers=UA)
            out = []
            for it in (j.get("collection") or {}).get("items", [])[:4]:
                href = it.get("href")
                title = ((it.get("data") or [{}])[0]).get("title", "NASA")
                if not href:
                    continue
                try:
                    urls = await self._get_json(s, href, headers=UA)
                except aiohttp.ClientError:
                    continue
                u = nasa_pick([x for x in urls if isinstance(x, str)], kind)
                if u:
                    out.append(Cand(u.replace("http://", "https://"), kind, "nasa", f"NASA: {title[:60]}", "https://images.nasa.gov"))
            return out
        if source == "wikimedia":
            ft = "video" if kind == "video" else "bitmap"
            j = await self._get_json(s, COMMONS, params={
                "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q} filetype:{ft}",
                "gsrnamespace": 6, "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata"}, headers=UA)
            return parse_commons(j, kind)
        if source == "archive" and kind == "video":
            qq = f"({q}) AND mediatype:movies AND (collection:prelinger OR collection:nasa OR collection:opensource_movies)"
            j = await self._get_json(s, f"{ARCHIVE}/advancedsearch.php", params={"q": qq, "fl[]": "identifier", "rows": 4, "output": "json"}, headers=UA)
            out = []
            for d in (j.get("response") or {}).get("docs", [])[:3]:
                ident = d.get("identifier")
                if not ident:
                    continue
                try:
                    meta = await self._get_json(s, f"{ARCHIVE}/metadata/{ident}", headers=UA)
                except aiohttp.ClientError:
                    continue
                f = archive_pick(meta.get("files", []))
                if f:
                    out.append(Cand(f"{ARCHIVE}/download/{ident}/{quote(f['name'])}", "video", "archive", f"Internet Archive: {ident}",
                                    f"{ARCHIVE}/details/{ident}", 0, 0, float(f.get("length") or 0)))
            return out
        return []

    async def _download(self, s: aiohttp.ClientSession, c: Cand, workdir: Path) -> Path | None:
        ext = Path(c.url.split("?")[0]).suffix.lower() or (".mp4" if c.kind == "video" else ".jpg")
        if len(ext) > 5:
            ext = ".mp4" if c.kind == "video" else ".jpg"
        path = workdir / f"stock_{uuid.uuid4().hex[:8]}{ext}"
        size = 0
        try:
            async with s.get(c.url, headers=UA) as r:
                if r.status != 200:
                    return None
                with open(path, "wb") as fh:
                    async for chunk in r.content.iter_chunked(256 * 1024):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise aiohttp.ClientError("too big")
                        fh.write(chunk)
        except (aiohttp.ClientError, TimeoutError, OSError):
            path.unlink(missing_ok=True)
            return None
        return path if size > 2000 else None

    async def find(self, query: str, portrait: bool, workdir: Path, kind: str = "video",
                   min_seconds: float = 0.0, exclude: set[str] | None = None) -> StockClip | None:
        q = " ".join((query or "").split())[:80]
        if not q:
            return None
        exclude = exclude if exclude is not None else set()
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            for source in self.active_sources():
                try:
                    cands = await self._candidates(s, source, q, portrait, kind)
                except (aiohttp.ClientError, TimeoutError, ValueError, json.JSONDecodeError) as e:
                    log.warning("stock_search_failed source=%s err=%s", source, type(e).__name__)
                    continue
                cands = [c for c in cands if c.url not in exclude]
                # prefer clips long enough for the scene
                cands.sort(key=lambda c: (c.duration and c.duration < min_seconds, _score(c.width, c.height, portrait)))
                for c in cands[:3]:
                    p = await self._download(s, c, workdir)
                    if p:
                        exclude.add(c.url)
                        return StockClip(p, c.kind, c.source, c.credit, c.page)
        return None
