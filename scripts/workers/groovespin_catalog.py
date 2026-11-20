"""Read the public GrooveSpin sitemap and release-specific offers."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import time
from urllib.parse import parse_qs, urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from bs4 import BeautifulSoup
import psycopg
import requests

from scripts.importers.common import run_import
from scripts.importers.import_groovespin import CONFIG, SHOP_DEFINITION
from scripts.workers.ean_progress import GitHubProgress, day_key, reserve


SHOP = "groovespin"
BASE = "https://www.groovespin.nl"
INDEX = f"{BASE}/storage/xml/nl/sitemap_nl.xml"
AGENT = "CuredPlant-Catalog"
FIELDS = ("timestamp", "master_id", "url", "artist", "title", "price_eur", "ean", "availability")
STOCK = {
    "InStock": "in_stock", "LimitedAvailability": "in_stock",
    "OutOfStock": "out_of_stock", "SoldOut": "out_of_stock",
    "PreOrder": "preorder", "BackOrder": "unknown",
}


class Blocked(RuntimeError):
    pass


def album_id(url):
    match = re.fullmatch(r"https://www\.groovespin\.nl/album/[^/?#]+-(\d+)", url)
    return int(match[1]) if match else None


class Source:
    def __init__(self, session):
        self.session = session
        self.session.headers["User-Agent"] = AGENT
        self.last_request = float("-inf")
        self.delay = 2.0
        self.robots = None
        rules = RobotFileParser()
        self.robots_lines = self.get(f"{BASE}/robots.txt").splitlines()
        rules.parse(self.robots_lines)
        self.robots = rules
        self.delay = max(self.delay, rules.crawl_delay(AGENT) or 0)
        # RobotFileParser does not implement wildcard paths or combine repeated
        # wildcard user-agent groups. Apply those exclusions conservatively.
        self.exclusions = []
        applies = False
        for line in self.robots_lines:
            key, _, value = line.split("#", 1)[0].partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                applies = value == "*" or value.lower() in AGENT.lower()
            elif applies and key == "disallow" and value:
                pattern = re.escape(value.removesuffix("$")).replace(r"\*", ".*")
                self.exclusions.append(re.compile(pattern + ("$" if value.endswith("$") else "")))

    def get(self, url, *, missing_ok=False):
        if not url.startswith(BASE + "/") or (self.robots and (
            not self.robots.can_fetch(AGENT, url)
            or any(rule.match(url.removeprefix(BASE)) for rule in self.exclusions)
        )):
            raise Blocked(f"Route excluded: {url}")
        time.sleep(max(0, self.last_request + self.delay - time.monotonic()))
        self.last_request = time.monotonic()
        response = self.session.get(url, timeout=(10, 25), allow_redirects=False)
        if response.status_code in (401, 403, 429):
            raise Blocked(f"HTTP {response.status_code}: {url}")
        if missing_ok and response.status_code in (404, 410):
            return None
        response.raise_for_status()
        if response.status_code != 200:
            raise RuntimeError(f"Unexpected HTTP {response.status_code}: {url}")
        return response.text

    def catalogue(self):
        index = ElementTree.fromstring(self.get(INDEX))
        sitemaps = [node.text for node in index.findall("{*}sitemap/{*}loc")
                    if node.text and re.fullmatch(re.escape(BASE) + r"/storage/xml/nl/sitemap-products-core-\d+\.xml", node.text)]
        if not sitemaps:
            raise ValueError("Product sitemaps missing")
        albums = {}
        for sitemap in sitemaps:
            root = ElementTree.fromstring(self.get(sitemap))
            entries = {album_id(node.text): node.text for node in root.findall("{*}url/{*}loc") if node.text}
            entries.pop(None, None)
            if not entries:
                raise ValueError("Empty product sitemap")
            albums.update(entries)
        return sorted(albums.items())


def valid_gtin(node):
    for field in ("gtin13", "gtin12", "gtin14", "gtin8"):
        value = str(node.get(field, ""))
        if not re.fullmatch(r"\d{8}|\d{12,14}", value) or len(set(value)) < 2:
            continue
        if sum(int(digit) * (1 if i % 2 == 0 else 3) for i, digit in enumerate(reversed(value))) % 10 == 0:
            return value
    return ""


def parse_offers(body, url, observed):
    graph = []
    for script in BeautifulSoup(body, "html.parser").select('script[type="application/ld+json"]'):
        document = json.loads(script.get_text())
        if isinstance(document, dict):
            graph.extend(document.get("@graph", [document]))
    album = next((node for node in graph if node.get("@type") == "MusicAlbum"), None)
    if album is None:
        raise ValueError(f"Album metadata missing: {url}")
    artist = album.get("byArtist")
    artist_name = artist.get("name", "") if isinstance(artist, dict) else ""
    for node in graph:
        name = node.get("name", "")
        if node.get("@type") != "Product" or not re.match(r"^(?:\d*LP|\d*EP|\d*SP|Vinyl)\b", name, re.I):
            continue
        offer = node.get("offers")
        if not isinstance(offer, dict) or offer.get("@type") != "Offer":
            continue
        if node.get("itemCondition") != "https://schema.org/NewCondition" or offer.get("itemCondition") != node["itemCondition"]:
            continue
        release = node.get("url", "")
        parts = urlsplit(release)
        if release.split("?", 1)[0] != url or parts.fragment or not re.fullmatch(r"releaseId=\d+", parts.query):
            continue
        if offer.get("url") != release or offer.get("priceCurrency") != "EUR":
            continue
        price = str(offer.get("price", ""))
        stock = STOCK.get(str(offer.get("availability", "")).rsplit("/", 1)[-1])
        if stock is None or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", price) or float(price) <= 0:
            continue
        yield dict(timestamp=observed, master_id=parse_qs(parts.query)["releaseId"][0], url=release,
                   artist=artist_name, title=album.get("name", ""), price_eur=price,
                   ean=valid_gtin(node), availability=stock)


def write_shop_details(dsn, details):
    with psycopg.connect(dsn, prepare_threshold=None) as connection:
        shop = connection.execute("select id from shops where domain=%s", (CONFIG.shop_domain,)).fetchone()
        if shop is None:
            raise RuntimeError("GrooveSpin shop does not exist after import")
        for destination, fee in details["destinations"].items():
            connection.execute("""
                insert into shop_shipping_destinations (shop_id,country_code,status,source_url,verified_at,note)
                values (%s,%s,'confirmed',%s,%s,%s)
                on conflict (shop_id,country_code) do update set
                    status=excluded.status, source_url=excluded.source_url,
                    verified_at=excluded.verified_at, note=excluded.note
                where shop_shipping_destinations.status in ('unknown','confirmed')
                and (shop_shipping_destinations.verified_at is null
                     or shop_shipping_destinations.verified_at <= excluded.verified_at)
                """, (shop[0], destination, details["shipping_source"], details["verified_at"],
                      f"Advertised EUR from {fee['pickup_eur']} pickup point / {fee['delivery_eur']} home delivery. "
                      "Exact charges vary at checkout. Shop based in Liberec, Czechia."))
        markets = connection.execute("""
            select country_code from shop_shipping_destinations
            where shop_id=%s and status='confirmed' and country_code in ('NL','BE')
            """, (shop[0],)).fetchall()
        if {row[0] for row in markets} != {"NL", "BE"}:
            raise RuntimeError("An explicit market exclusion needs review before shop activation")
        active_offers = connection.execute(
            "select count(*) from prices where shop_id=%s and is_active", (shop[0],)
        ).fetchone()[0]
        if not active_offers:
            raise RuntimeError("GrooveSpin has no active offers after import")
        connection.execute(
            "update shops set is_active=true, updated_at=now() where id=%s and not is_active",
            (shop[0],),
        )
    return active_offers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("output/groovespin"))
    args = parser.parse_args()
    if not 1 <= args.limit <= (250 if args.write else 20):
        parser.error("Use 1–20 albums for a pilot or 1–250 for a write batch")
    dsn = os.environ.get("DATABASE_URL")
    if args.write and not dsn:
        parser.error("DATABASE_URL is required for a write batch")
    progress = GitHubProgress(SHOP) if args.write else None
    today = day_key()
    state = progress.load() if progress else {"cursor": {}}
    cursor = state["cursor"]
    if cursor.get("blocked_on") == today:
        print("GrooveSpin access was blocked earlier today")
        return
    limit = reserve(state, args.limit, today) if progress else args.limit
    if not limit:
        print("GrooveSpin daily budget exhausted")
        return
    if progress:
        progress.save(state)
    args.output.mkdir(parents=True, exist_ok=True)
    csv_path = args.output / "offers.csv"
    details = json.loads(Path("config/groovespin-shop.json").read_text())
    last = cursor.get("last_album_id", 0)
    observed = datetime.now(timezone.utc).isoformat()
    with requests.Session() as session, csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        try:
            source = Source(session)
            albums = source.catalogue()
            batch = [(key, url) for key, url in albums if key > last][:limit]
            if not batch:
                batch = albums[:limit]
            for key, url in batch:
                if day_key() != today:
                    raise RuntimeError("Batch crossed the daily quota boundary; rerun on the new day")
                body = source.get(url, missing_ok=True)
                if body is not None:
                    writer.writerows(parse_offers(body, url, observed))
        except Blocked:
            if progress:
                cursor["blocked_on"] = today
                progress.save(state)
            raise

    summary_path = args.output / "import-summary.json"
    with csv_path.open(encoding="utf-8", newline="") as stream:
        importable = any(SHOP_DEFINITION.row_mapper(row, line)[0] is not None
                         for line, row in enumerate(csv.DictReader(stream), start=2))
    run_import(CONFIG, str(csv_path), SHOP_DEFINITION.row_mapper, dry_run=not args.write or not importable,
               rejects_path=str(args.output / "rejects.csv"), summary_path=str(summary_path))
    summary = json.loads(summary_path.read_text())
    if progress:
        if summary["accepted_records"]:
            active_offers = write_shop_details(dsn, details)
            print(f"GrooveSpin registered for NL and BE with {active_offers} active offers.")
        cursor["last_album_id"] = batch[-1][0]
        progress.save(state)
    print(f"Album pages: {len(batch)} of {len(albums)}. Last album ID: {batch[-1][0]}.")
    if not args.write and not summary["accepted_records"]:
        raise RuntimeError("Pilot yielded no importable offers")


if __name__ == "__main__":
    main()
