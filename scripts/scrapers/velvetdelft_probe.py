"""Read-only Velvet Delft discovery probe. NOT a production importer.
Never writes to Supabase. Uses robots.txt and conservative request pacing.
Unverified selectors/filters are deliberately NOT treated as production-ready.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

BASE = "https://www.velvetdelft.nl"
from scripts.scrapers.velvetdelft import GENRES

RELEASE_PATH = re.compile(r"^/(?:nl|en)/release/(\d+)/", re.I)
USER_AGENT = "VinylofyVelvetDelftResearch/0.1"


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def extract_release_links(html: str, page_url: str) -> list[dict[str, str]]:
    parser = LinkParser()
    parser.feed(html)
    found = {}
    for href in parser.links:
        url = urljoin(page_url, href).split("#", 1)[0]
        parsed = urlparse(url)
        match = RELEASE_PATH.match(parsed.path)
        if parsed.hostname not in ("velvetdelft.nl", "www.velvetdelft.nl") or not match:
            continue
        found.setdefault(match.group(1), {"release_id": match.group(1), "source_url": url})
    return list(found.values())


def fetch(url: str, robots: RobotFileParser, timeout: int) -> str:
    if not robots.can_fetch(USER_AGENT, url):
        raise RuntimeError("robots.txt disallows " + url)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read(4_000_000).decode(charset, errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--genre", choices=GENRES, default="prog")
    ap.add_argument("--max-pages", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if args.max_pages != 1:
        ap.error("Only the first page is supported until actual pagination/filter parameters are verified")
    if args.delay < 2:
        ap.error("--delay must be at least 2 seconds")
    robots = RobotFileParser()
    robots.set_url(BASE + "/robots.txt")
    try:
        robots.read()
        if robots.disallow_all:
            raise RuntimeError("robots unavailable or disallow all; fail closed")
        url = f"{BASE}/nl/pagina/{args.genre}"
        rows = extract_release_links(fetch(url, robots, args.timeout), url)
        result = {"shop": "velvetdelft", "mode": "read_only_probe", "genre": args.genre,
                  "source_url": url, "release_count": len(rows), "releases": rows,
                  "price_verified": False, "availability_verified": False,
                  "vinyl_filter_verified": False, "database_write": False}
        report = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            from pathlib import Path
            Path(args.out).write_text(report, encoding="utf-8")
        else:
            print(report)
        return 0 if rows else 2
    except Exception as exc:
        print(json.dumps({"shop": "velvetdelft", "status": "failed", "error": str(exc),
                          "database_write": False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
