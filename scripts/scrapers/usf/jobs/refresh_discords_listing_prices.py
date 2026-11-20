#!/usr/bin/env python3
"""Listing-first Discords price and availability refresh."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import time

from scripts.scrapers.discords import (PAGE_SIZE, SHOP_COUNTRY, SHOP_DOMAIN, SHOP_ID,
    SHOP_NAME, fetch_page, listing_record, make_session)
from scripts.scrapers.usf.core.db import db_connection
from scripts.scrapers.usf.core.link_registry import upsert_discovered_links
from scripts.scrapers.usf.core.listing_price_sync import ListingOffer, sync_listing_offers
from scripts.scrapers.usf.core.models import DiscoveredLink

SHOPIFY_PRODUCTS_JSON_MAX_PAGES = 250


def collect(*, max_pages: int, page_size: int, delay: float, start_page: int = 1,
            progress_file: str | None = None):
    session, seen_at = make_session(), datetime.now(timezone.utc)
    links: dict[str, DiscoveredLink] = {}
    offers: dict[str, ListingOffer] = {}
    signatures: set[tuple[str, ...]] = set()
    page, last_page, stop, pages_processed = start_page, start_page, "not_started", 0
    try:
        while max_pages == 0 or pages_processed < max_pages:
            last_page = page
            products = fetch_page(session, page, page_size)
            pages_processed += 1
            if not products:
                stop = "empty_page"
                break
            records = [row for product in products if (row := listing_record(product, page=page, seen_at=seen_at))]
            signature = tuple(sorted(row["product_url"] for row in records))
            if not signature or signature in signatures:
                stop = "empty_or_repeated_page"
                break
            signatures.add(signature)
            for row in records:
                url = row["product_url"]
                payload = {**row, "price_source": "collection_products_json", "listing_seen_at": seen_at.isoformat()}
                links[url] = DiscoveredLink(shop_id=SHOP_ID, source_url=url,
                    source_product_id=row["product_id"], payload=payload)
                offers[url] = ListingOffer(shop_name=SHOP_NAME, shop_domain=SHOP_DOMAIN,
                    shop_country=SHOP_COUNTRY, source_url=url, price=row["price"],
                    availability=row["availability"], currency="EUR", seen_at=seen_at, raw=payload)
            print("[DISCORDS-LISTING]", {"page": page, "raw": len(products), "vinyl": len(records), "total": len(links)}, flush=True)
            if len(products) < page_size:
                stop = "partial_last_page"
                break
            # Shopify's public products.json endpoint caps a collection at
            # 25,000 records (250 pages at limit=100); requesting page 251
            # returns HTTP 400 even after a complete, valid feed read.
            if page_size == PAGE_SIZE and page >= SHOPIFY_PRODUCTS_JSON_MAX_PAGES:
                stop = "shopify_products_json_25000_record_cap"
                break
            page += 1
            time.sleep(delay)
        else:
            stop = "max_pages_limit"
    finally:
        session.close()
    if progress_file:
        from pathlib import Path
        import json
        progress = {"start_page": start_page, "pages_processed": pages_processed,
                    "last_page": last_page, "next_page": page if stop == "max_pages_limit" else 1,
                    "stop": stop}
        Path(progress_file).write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
    return list(links.values()), list(offers.values()), seen_at, stop


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--progress-file")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.max_pages < 0 or not 1 <= args.start_page <= SHOPIFY_PRODUCTS_JSON_MAX_PAGES or not 1 <= args.page_size <= PAGE_SIZE or args.delay < 0:
        parser.error("invalid bounded listing arguments")
    links, offers, _, stop = collect(max_pages=args.max_pages, page_size=args.page_size, delay=args.delay,
                                      start_page=args.start_page, progress_file=args.progress_file)
    print("[DISCORDS-LISTING-SUMMARY]", {"links": len(links), "offers": len(offers), "stop": stop, "write": args.write}, flush=True)
    if stop == "empty_or_repeated_page":
        raise SystemExit("[ERROR] Discords pagination repeated a page; refusing this partial price batch")
    if args.progress_file:
        from pathlib import Path
        import json
        progress = json.loads(Path(args.progress_file).read_text(encoding="utf-8"))
    else:
        progress = {}
    terminal_empty_probe = bool(args.progress_file and stop == "empty_page"
                                and progress.get("pages_processed") == 1 and args.start_page > 1)
    if not links and terminal_empty_probe:
        return 0
    if not links or len(offers) / len(links) < .9:
        raise SystemExit("[ERROR] Discords listing coverage failed safe guards")
    if not args.write:
        return 0
    result = upsert_discovered_links(links)
    with db_connection() as conn:
        stats = sync_listing_offers(conn, offers, write=True)
    print("[DISCORDS-LISTING-WRITE]", {"registry": vars(result), "prices": vars(stats)}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
