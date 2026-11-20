"""Refresh known GrooveSpin releases from a permitted catalogue listing."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from bs4 import BeautifulSoup
import requests

from scripts.workers.groovespin_catalog import BASE, SHOP, Source, album_id
from scripts.workers.price_database import update_existing


PRICE = re.compile(r"([0-9]+(?:\.[0-9]{3})*),([0-9]{2})\s*€")
VINYL_FORMATS = {"LP", "EP", "SP", "Vinyl"}
FIELDS = ("source_url", "price", "currency", "availability")
AVAILABILITY = {"Op voorraad": "in_stock", "Niet op voorraad": "out_of_stock",
                "Uitverkocht": "out_of_stock", "Pre-order": "preorder"}


def exact_offer(item):
    # The listing groups products by album. Even a release_id on a group
    # does not establish ownership of a "from" price or of the other variants.
    if item.get("used") != 0 or item.get("condition_id") != 1:
        return None
    formats = {entry.get("name") for entry in item.get("formats", [])}
    if not formats or not formats <= VINYL_FORMATS:
        return None
    product = item.get("id")
    release = item.get("release_id")
    if (type(product) is not int or product < 1 or item.get("productIds") != [product]
            or item.get("items_count") != 1 or type(release) is not int or release < 1):
        return None
    url = item.get("url") or ""
    match = PRICE.fullmatch(str(item.get("price") or "").strip())
    if album_id(url) is None or match is None:
        return None
    price = f"{match[1].replace('.', '')}.{match[2]}"
    if float(price) <= 0:
        return None
    availability = (item.get("available") or {}).get("name_localised")
    return {"source_url": f"{url}?releaseId={release}", "price": price, "currency": "EUR",
            "availability": AVAILABILITY.get(availability, "unknown")}


def parse_listing(body):
    app = BeautifulSoup(body, "lxml").select_one("#app[data-page]")
    if app is None:
        raise ValueError("GrooveSpin listing data missing")
    page = json.loads(app["data-page"])
    props = page.get("props", {})
    if page.get("component") != "ProductListPage" or props.get("currentCurrency") != "EUR":
        raise ValueError("Expected the EUR GrooveSpin catalogue")
    listing = props["masters"]
    if not isinstance(listing["data"], list):
        raise ValueError("Unexpected GrooveSpin listing rows")
    return listing


def route_key(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "www.groovespin.nl" or parts.fragment:
        raise ValueError("Expected a public HTTPS listing on www.groovespin.nl")
    if not parts.path.startswith("/") or parts.path.startswith("//"):
        raise ValueError("Invalid listing path")
    query = parse_qsl(parts.query, keep_blank_values=True)
    pages = [value for key, value in query if key == "page"]
    if pages and (len(pages) != 1 or not re.fullmatch(r"[1-9][0-9]*", pages[0])):
        raise ValueError("Invalid page parameter")
    return parts.path, sorted((key, value) for key, value in query if key != "page"), int(pages[0]) if pages else 1


def crawl(source, start_url, max_pages):
    path, filters, first = route_key(start_url)
    if first != 1:
        raise ValueError("Start the daily price round on page one")
    records = {}
    seen = set()
    url = start_url
    total = last = None
    for number in range(1, max_pages + 1):
        if route_key(url) != (path, filters, number):
            raise ValueError("Listing pagination skipped a page or changed filters")
        listing = parse_listing(source.get(url))
        if listing["current_page"] != number or listing.get("has_exact_total") is not True:
            raise ValueError("Listing did not report an exact page and catalogue size")
        if number == 1:
            total, last = listing["total"], listing["last_page"]
            if type(total) is not int or total < 1 or type(last) is not int or last < 1:
                raise ValueError("Listing catalogue is empty or invalid")
        if listing["total"] != total or listing["last_page"] != last:
            raise ValueError("Catalogue size changed during pagination")
        for item in listing["data"]:
            key = item.get("master_id")
            if type(key) is not int or key < 1 or key in seen:
                raise ValueError("Listing contains a missing or repeated album ID")
            seen.add(key)
            record = exact_offer(item)
            if record:
                records[record["source_url"]] = record
        following = listing["next_page_url"]
        if following is None:
            if number != last or len(seen) != total:
                raise ValueError("Listing ended before all declared catalogue records were visited")
            return records, {"complete": True, "pages": number, "albums": len(seen), "declared_albums": total}
        if number >= last:
            raise ValueError("Listing has a next link beyond the declared last page")
        next_url = urljoin(BASE, following)
        if route_key(next_url) != (path, filters, number + 1):
            raise ValueError("Listing next link changes the route, page or filters")
        url = next_url
    return records, {"complete": False, "pages": max_pages, "albums": len(seen), "declared_albums": total}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("output/groovespin-prices"))
    args = parser.parse_args()
    if args.max_pages < 1:
        parser.error("--max-pages must be positive")
    if args.write and not os.environ.get("DATABASE_URL"):
        parser.error("DATABASE_URL is required for a write run")
    route_key(args.url)
    started_at = datetime.now(timezone.utc)
    with requests.Session() as session:
        records, summary = crawl(Source(session), args.url, args.max_pages)
    summary.update(exact_offers=len(records), albums_without_exact_offer=summary["albums"] - len(records))
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "observed-prices.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records.values())
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)
    if args.write:
        # Require every listing group to have an exact eligible offer before a
        # price run can claim full coverage. No changes on ambiguous snapshots.
        if not summary["complete"] or summary["albums_without_exact_offer"]:
            raise RuntimeError("Full release-level coverage was not verified; no prices written")
        summary["database"] = update_existing(SHOP, list(records.values()), started_at)
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
