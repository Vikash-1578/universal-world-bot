"""Web access for the Research agent: search (Wikipedia always; Brave if a `brave:` key is in keys.txt) and page fetch.
Everything the agents claim must trace back to a page fetched here. Nothing is cached as "truth" — only as evidence."""
from __future__ import annotations

import asyncio
import ipaddress
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, unquote, urlparse

import aiohttp

from app.observability.log import get_logger

log = get_logger(__name__)
MAX_BYTES = 1_500_000
# Wikipedia asks for a descriptive agent; many other sites block anything that does not look like a browser.
WIKI_UA = {"User-Agent": "UniversalWorldBot/1.0 (personal, non-commercial research tool; Python aiohttp)"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
A_SUFFIX = (".gov", ".edu", ".mil", ".gov.in", ".ac.in", ".gov.uk", ".ac.uk", ".nic.in")
A_DOMAINS = {"nasa.gov", "britannica.com", "nature.com", "science.org", "who.int", "un.org", "unesco.org", "nih.gov", "si.edu",
             "nationalgeographic.com", "smithsonianmag.com", "esa.int", "loc.gov", "archive.org"}
B_DOMAINS = {"wikipedia.org", "bbc.com", "bbc.co.uk", "reuters.com", "apnews.com", "history.com", "worldhistory.org",
             "livescience.com", "scientificamerican.com", "nytimes.com", "theguardian.com", "thehindu.com"}
TWO_LEVEL = ("co.uk", "gov.uk", "ac.uk", "gov.in", "ac.in", "nic.in", "com.au", "co.in", "co.jp")


def domain_of(url: str) -> str:
    """Registrable-ish domain: en.wikipedia.org and hi.wikipedia.org both -> wikipedia.org (they are ONE source)."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in TWO_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def tier_of(domain: str) -> str:
    if domain in A_DOMAINS or domain.endswith(A_SUFFIX):
        return "A"
    return "B" if domain in B_DOMAINS else "C"


def safe_url(url: str) -> bool:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    h = u.hostname.lower()
    if h == "localhost" or h.endswith((".local", ".internal")):
        return False
    try:
        ip = ipaddress.ip_address(h)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
    except ValueError:
        return True


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        self._in_title = tag == "title"
        if tag in ("p", "br", "li", "h1", "h2", "h3", "div"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.out.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    p = _Text()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 - broken HTML: use what we got
        pass
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return " ".join(p.title.split())[:200], text


_DDG_A = re.compile(r"<a\s[^>]*class=\"[^\"]*result__a[^\"]*\"[^>]*>", re.I | re.S)
_HREF = re.compile(r"href=\"([^\"]+)\"", re.I)


def parse_ddg(html: str) -> list[dict]:
    """DuckDuckGo HTML results -> [{url, title}] (their redirect links are unwrapped). Best effort: layout may change."""
    out = []
    for m in _DDG_A.finditer(html):
        h = _HREF.search(m.group(0))
        if not h:
            continue
        href = h.group(1).replace("&amp;", "&")
        if href.startswith("//"):
            href = "https:" + href
        q = parse_qs(urlparse(href).query)
        url = unquote(q["uddg"][0]) if "uddg" in q else href
        end = html.find("</a>", m.end())
        title = re.sub(r"<[^>]+>", "", html[m.end():end if end > 0 else m.end() + 200])
        if safe_url(url):
            out.append({"url": url, "title": " ".join(title.split())[:120]})
    return out


class Web:
    def __init__(self, brave_key: str = "", timeout: float = 15.0) -> None:
        self.brave_key = brave_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._sem = asyncio.Semaphore(3)  # be polite: a burst of parallel requests gets rate-limited (HTTP 429)
        self.errors: list[str] = []      # last fetch problems, e.g. "britannica.com: HTTP 403"

    async def _get_json(self, s: aiohttp.ClientSession, url: str, **kw) -> dict:
        async with s.get(url, **kw) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def search(self, query: str, limit: int = 4) -> list[dict]:
        """-> [{url, title}] from Wikipedia (+ Brave). Failures return what worked; never raises."""
        hits: list[dict] = []
        async with aiohttp.ClientSession(timeout=self.timeout, headers=WIKI_UA) as s:
            try:
                d = await self._get_json(s, "https://en.wikipedia.org/w/api.php", params={
                    "action": "query", "list": "search", "srsearch": query, "srlimit": limit, "format": "json"})
                for h in d.get("query", {}).get("search", []):
                    t = h["title"]
                    hits.append({"url": "https://en.wikipedia.org/wiki/" + quote(t.replace(" ", "_")), "title": t})
            except Exception as e:  # noqa: BLE001
                log.warning("wiki_search_failed %s", type(e).__name__)
            if self.brave_key:
                try:
                    d = await self._get_json(s, "https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": limit},
                                             headers={"X-Subscription-Token": self.brave_key, "Accept": "application/json"})
                    for h in d.get("web", {}).get("results", []):
                        if h.get("url") and safe_url(h["url"]):
                            hits.append({"url": h["url"], "title": str(h.get("title", ""))[:120]})
                except Exception as e:  # noqa: BLE001
                    log.warning("brave_search_failed %s", type(e).__name__)
        if len({domain_of(h["url"]) for h in hits}) < 3:  # keyless fallback so the owner is not stuck with Wikipedia only
            try:
                async with aiohttp.ClientSession(timeout=self.timeout, headers=UA) as s:
                    async with s.get("https://html.duckduckgo.com/html/", params={"q": query}) as r:
                        r.raise_for_status()
                        hits += parse_ddg(await r.text())[:limit + 2]
            except Exception as e:  # noqa: BLE001
                log.warning("ddg_search_failed %s", type(e).__name__)
        seen, out = set(), []
        for h in hits:
            if h["url"] not in seen:
                seen.add(h["url"])
                out.append(h)
        return out

    async def fetch(self, url: str) -> dict | None:
        """-> {url, title, text} or None. Wikipedia via its API (clean text); other pages via HTML->text."""
        if not safe_url(url):
            return None
        async with self._sem:
            for attempt in range(2):
                try:
                    return await self._fetch_once(url)
                except aiohttp.ClientResponseError as e:
                    if e.status == 429 and attempt == 0:
                        await asyncio.sleep(2.5)  # rate limited: wait once, then retry
                        continue
                    self._note(url, f"HTTP {e.status}")
                    return None
                except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError) as e:
                    self._note(url, type(e).__name__)
                    return None
        return None

    def _note(self, url: str, why: str) -> None:
        msg = f"{domain_of(url)}: {why}"
        self.errors = (self.errors + [msg])[-20:]
        log.warning("fetch_failed %s", msg)

    async def _fetch_once(self, url: str) -> dict | None:
        wiki = domain_of(url) == "wikipedia.org" and "/wiki/" in url
        async with aiohttp.ClientSession(timeout=self.timeout, headers=WIKI_UA if wiki else UA) as s:
            if wiki:
                host = urlparse(url).hostname
                title = unquote(url.split("/wiki/", 1)[1]).replace("_", " ")
                d = await self._get_json(s, f"https://{host}/w/api.php", params={
                    "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": title, "format": "json"})
                page = next(iter(d.get("query", {}).get("pages", {}).values()), {})
                text = page.get("extract") or ""
                return {"url": url, "title": page.get("title", ""), "text": text} if text else None
            async with s.get(url, allow_redirects=True) as r:
                r.raise_for_status()
                if not safe_url(str(r.url)) or "html" not in r.headers.get("Content-Type", "html"):
                    return None
                raw = await r.content.read(MAX_BYTES)
            title, text = html_to_text(raw.decode(r.charset or "utf-8", errors="ignore"))
            return {"url": url, "title": title, "text": text} if len(text) > 200 else None
