"""Quick self-test of web access:  python -m app.agents.webcheck "bermuda triangle"
Shows what search returns and whether each page can be downloaded (HTTP status), so problems are visible."""
from __future__ import annotations

import asyncio
import sys

from app.agents.web import Web, domain_of
from app.core.config import load_settings


async def main(query: str) -> None:
    web = Web(load_settings().key("brave"))
    hits = await web.search(query, 5)
    print(f"Search: {len(hits)} results, {len({domain_of(h['url']) for h in hits})} alag sites")
    for h in hits:
        p = await web.fetch(h["url"])
        print(("OK   " if p else "FAIL ") + domain_of(h["url"]).ljust(24) + (f"{len(p['text'])} chars" if p else "") + "  " + h["url"][:70])
    if web.errors:
        print("\nErrors:", *web.errors, sep="\n  ")


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "bermuda triangle"))
