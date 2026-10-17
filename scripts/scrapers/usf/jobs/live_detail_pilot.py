"""Bounded, read-only site verification using each shop's own parser.

Unlike a database-queue preview this fetches real products. No database helper
is called. The JSON artifact is also written when discovery or HTTP fails.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from scripts.importers.common import strict_normalize_gtin

SHOPS = (
    "cdhal", "colouredvinyl", "dgmoutlet", "everythingjazz", "fiftiesstore",
    "myrecordstore", "northendhaarlem", "shop3345", "soundshaarlem", "soundsvenlo",
)


def get(session, url):
    response = session.get(url, timeout=(10, 30))
    response.raise_for_status()
    return response


def link_row(link):
    return {"source_url": link.source_url, "payload": link.payload,
            "source_product_id": link.source_product_id}


def discover(shop, session, limit):
    now = datetime.now(timezone.utc)
    if shop == "cdhal":
        from scripts.scrapers.usf.jobs import refresh_cdhal_listing_prices as source
        url = source.listing_url(1)
        links, _, _ = source.parse_listing_page(get(session, url).text,
            source_listing_url=url, page=1, seen_at=now)
        return [link_row(x) for x in links][:limit]
    if shop == "colouredvinyl":
        from scripts.scrapers.usf.jobs import refresh_colouredvinyl_listing_prices as source
        url = source.listing_url_for_page(1)
        links, _, _ = source.parse_listing_page(get(session, url).text,
            listing_url=url, page=1, seen_at=now, debug=False)
        return [link_row(x) for x in links][:limit]
    if shop == "everythingjazz":
        from scripts.scrapers.usf.jobs import refresh_everythingjazz_listing_prices as source
        products = source.fetch_page(session, page=1, limit=50, timeout=30)
        links = [source.parse_product(p, page=1, seen_at=now)[0] for p in products]
        return [link_row(x) for x in links if x][:limit]
    if shop == "fiftiesstore":
        from scripts.scrapers.usf.jobs import refresh_fiftiesstore_listing_prices as source
        products = source.fetch_batch(0, limit).get("product_data", [])
        return [{"source_url": source.normalize_url(p["url"]), "payload": {
            "title": p["name"], "price": source.price(p.get("price")),
            "ean": source.ean_from_sku(p.get("sku")), "sku": p.get("sku"),
            "availability": "unknown", "price_source": "clerk_api"}}
            for p in products[:limit]]
    if shop == "myrecordstore":
        from scripts.scrapers.usf.jobs import refresh_myrecordstore_listing_prices as source
        url = source.SEED_URL
        links, _ = source.parse_listing_page(get(session, url).text,
            listing_url=url, page=1, seen_at=now)
        return [link_row(x) for x in links][:limit]
    if shop == "northendhaarlem":
        from scripts.scrapers.usf.jobs import refresh_northendhaarlem_listing_prices as source
        seed = source.CATEGORY_SEEDS[0]
        url = source.category_url(seed, 1)
        rows = source.parse_listing_page(get(session, url).text, discovery_url=url,
            seed=seed, page=1, seen_at=now.isoformat())
        return [link_row(x.link) for x in rows][:limit]
    if shop == "soundsvenlo":
        from scripts.scrapers.usf.jobs import refresh_soundsvenlo_listing_prices as source
        url = source.listing_url_for_page(1)
        links, _ = source.parse_listing_page(get(session, url).text,
            listing_url=url, page=1, seen_at=now, debug=False)
        return [link_row(x) for x in links][:limit]
    if shop == "soundshaarlem":
        from scripts.scrapers.usf.jobs import refresh_soundshaarlem_listing_prices as source
        url = source.SEED_URLS[0]
        links, _ = source.parse_collection_page(get(session, url).text,
            seed_url=url, listing_url=url, page=1, seen_at=now)
        return [link_row(x) for x in links][:limit]
    if shop == "shop3345":
        products = get(session, "https://3345.nl/products.json?limit=100").json()["products"]
        rows = []
        for p in products:
            title = p.get("title", "")
            if not re.search(r"\b(?:LP|vinyl|12[ -]?inch|7[ -]?inch)\b", title, re.I):
                continue
            tags = " ".join(p.get("tags", [])) if isinstance(p.get("tags"), list) else str(p.get("tags", ""))
            if re.search(r"\b(?:used|second[ -]?hand|tweedehands)\b", title + " " + tags, re.I):
                continue
            variants = p.get("variants", [])
            available = [v for v in variants if v.get("available")]
            prices = {v.get("price") for v in available or variants}
            rows.append({"source_url": "https://3345.nl/products/" + p["handle"],
                "payload": {"title": title, "price": next(iter(prices)) if len(prices) == 1 else None,
                "availability": "in_stock" if available else "out_of_stock",
                "is_secondhand": False, "listing_cta_add_to_cart": bool(available)}})
        return rows[:limit]
    if shop == "dgmoutlet":
        from scripts.scrapers.dgmoutlet import DGMOutletLPScraper, BASE_URL
        source = DGMOutletLPScraper("unused.csv", max_pages=1)
        url = BASE_URL.format(page=1)
        soup = BeautifulSoup(get(session, url).text, "html.parser")
        rows = []
        # _parse_card also fetches the individual detail page for stock evidence.
        for card in soup.select("div.card.product-box.box-standard")[:limit]:
            row = source._parse_card(card, 1, url, now.isoformat())
            if row:
                payload = asdict(row)
                payload.update(price=row.price_current, title=row.raw_name)
                rows.append({"source_url": row.url, "payload": payload, "detail_checked": True})
            time.sleep(1.5)
        return rows
    raise ValueError(shop)


def parse(shop, session, row):
    url, payload = row["source_url"], row["payload"]
    if shop == "dgmoutlet":
        # _parse_card already fetched the same product detail for availability.
        return payload.get("ean"), payload.get("title"), None
    if shop == "everythingjazz":
        from scripts.scrapers.usf.jobs import detail_everythingjazz as source
        data = get(session, source.product_js_url(url)).json()
        parsed = source.parse_detail(link=row, payload=data, detail_url=source.product_js_url(url))
        return parsed["ean_raw"], parsed["title_raw"], parsed["payload"].get("detail_issue")
    if shop == "cdhal":
        from scripts.scrapers.usf.jobs import detail_cdhal as source
        response = source.request_detail_page(session, url, max_attempts=2)
        response.raise_for_status()
        html = response.text
    else:
        html = get(session, url).text
    if shop == "cdhal":
        from scripts.scrapers.usf.jobs import detail_cdhal as source
        detail = source.parse_detail_html(html, source_url=url, payload=payload)
        return detail["ean_raw"], detail["title_raw"], None
    if shop == "colouredvinyl":
        from scripts.scrapers.usf.jobs import detail_colouredvinyl as source
        detail = source.parse_detail(html=html, source_url=url, listing_payload=payload)
        return detail["ean"], detail["title_raw"], None
    if shop == "myrecordstore":
        from scripts.scrapers.usf.jobs import detail_myrecordstore as source
        soup = BeautifulSoup(html, "html.parser")
        title = soup.select_one("h1")
        return source.extract_ean(soup, source.clean(soup.get_text(" ", strip=True))), title.get_text(" ", strip=True) if title else None, None
    if shop == "northendhaarlem":
        from scripts.scrapers.usf.jobs import detail_northendhaarlem as source
        detail = source.parse_detail_page(html, listing_payload=payload)
        return detail["ean"], detail["title_raw"], None
    if shop == "soundshaarlem":
        from scripts.scrapers.usf.jobs import detail_soundshaarlem as source
        detail = source.parse_product_page(html, url, payload)
        return detail["ean_raw"], source.title_raw_from_detail(detail, payload), None
    if shop in {"soundsvenlo", "shop3345"}:
        if shop == "soundsvenlo":
            from scripts.scrapers.usf.jobs import detail_soundsvenlo as source
        else:
            from scripts.scrapers.usf.jobs import detail_shop3345 as source
        return source.extract_ean(html, url), source.build_title_raw(payload, html), None
    if shop == "dgmoutlet":
        soup = BeautifulSoup(html, "html.parser")
        values = [node.get("content") for node in soup.select('[itemprop^="gtin"][content]')]
        # This Shopware shop exposes the real GTIN as the listing SKU / URL.
        values.append(payload.get("ean"))
        eans = {strict_normalize_gtin(v) for v in values} - {None}
        return next(iter(eans)) if len(eans) == 1 else None, payload.get("title"), None
    if shop == "fiftiesstore":
        # Magento's labelled product attributes are scoped to this product only.
        soup = BeautifulSoup(html, "html.parser")
        values = [payload.get("ean")]
        for tr in soup.select("table#product-attribute-specs-table tr"):
            label = tr.select_one("th")
            value = tr.select_one("td")
            if label and value and re.search(r"\b(?:ean|barcode|gtin)\b", label.get_text(), re.I):
                values.append(value.get_text(strip=True))
        eans = {strict_normalize_gtin(v) for v in values} - {None}
        return next(iter(eans)) if len(eans) == 1 else None, payload.get("title"), None
    raise ValueError(shop)


def run(shop, limit, delay, attempt):
    summary = {"shop": shop, "attempt": attempt, "write": False,
        "time": datetime.now(timezone.utc).isoformat(), "discovered": 0,
        "fetched": 0, "valid_eans": 0, "missing_ean": 0, "errors": [], "records": []}
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8"})
    try:
        rows = discover(shop, session, limit)
        summary["discovered"] = len(rows)
        for row in rows:
            record = {"url": row["source_url"], "listing_price": row["payload"].get("price")}
            try:
                ean, title, issue = parse(shop, session, row)
                valid = strict_normalize_gtin(ean)
                record.update(title=title, ean=valid, observed_ean=ean, issue=issue)
                summary["fetched"] += 1
                summary["valid_eans" if valid else "missing_ean"] += 1
            except Exception as exc:
                record["error"] = str(exc)
                summary["errors"].append({"url": row["source_url"], "error": str(exc)})
            summary["records"].append(record)
            print("[LIVE-DETAIL]", json.dumps(record, ensure_ascii=False), flush=True)
            if record.get("error") and ("403" in record["error"] or "429" in record["error"]):
                break
            time.sleep(max(delay, 2.0) if shop in {"cdhal", "dgmoutlet"} else delay)
    except Exception as exc:
        summary["errors"].append({"stage": "discovery", "error": str(exc)})
    # Source-missing EANs are visible, but HTTP failures/empty queues cannot pass.
    summary["status"] = "green" if summary["valid_eans"] >= min(3, limit) and not summary["errors"] else "red"
    output = Path("output/ean-pilots") / f"{shop}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with output.with_suffix(".jsonl").open("a", encoding="utf-8") as history:
        history.write(json.dumps(summary, ensure_ascii=False) + "\n")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(f"### {shop}: {summary['status']}\n\n"
                f"Detail fetched: {summary['fetched']}; valid GTIN: {summary['valid_eans']}; "
                f"source misses: {summary['missing_ean']}; errors: {len(summary['errors'])}. "
                "Database writes: 0. Full evidence is in the artifact.\n")
    print("[LIVE-DETAIL-SUMMARY]", json.dumps({k: v for k, v in summary.items() if k != "records"}), flush=True)
    return 0 if summary["status"] == "green" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop", choices=SHOPS, required=True)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--attempt", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--register-only", action="store_true",
                        help="Explicit production bootstrap: registry only, no prices or delisting")
    args = parser.parse_args()
    if not 1 <= args.limit <= 250 or args.delay < 0:
        parser.error("limit must be 1..250; delay must be nonnegative")
    if args.register_only:
        from scripts.scrapers.usf.core.db import db_connection
        from psycopg.types.json import Jsonb
        # Preserve existing detail metadata and counters when refreshing listing
        # evidence. The earlier listing commands also changed public prices and
        # could delist a catalog based on a bounded sample.
        with requests.Session() as session:
            rows = discover(args.shop, session, args.limit)
        if not rows:
            raise SystemExit("Live discovery is empty; registry left unchanged")
        with db_connection() as conn, conn.cursor() as cur:
            for row in rows:
                cur.execute("""
                    insert into public.shop_product_links
                        (shop_id, source_url, source_product_id, first_seen_at,
                         last_seen_at, status, payload)
                    values (%s,%s,%s,now(),now(),'active',%s)
                    on conflict (shop_id, source_url) do update set
                        last_seen_at=now(), status='active',
                        payload=coalesce(shop_product_links.payload,'{}'::jsonb) || excluded.payload
                    """, (args.shop, row["source_url"], row.get("source_product_id"), Jsonb(row["payload"])))
        print(f"[DETAIL-REGISTRY] registered={len(rows)}; public price writes=0; delisting=0")
        return 0
    return run(args.shop, args.limit, args.delay, args.attempt)


if __name__ == "__main__":
    raise SystemExit(main())
