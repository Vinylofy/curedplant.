"""Daily Muziker artist/title catalog capture with explicit database writes.

The shop has no dependable EAN field. This worker stores only public listing
evidence and queues the record for the existing album-offer matching pipeline.
It never invents an identifier and stops on access/rate-limit responses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import psycopg
from psycopg.types.json import Jsonb
from bs4 import BeautifulSoup

from scripts.workers.album_offer_sources import Transport, approved_url

DOMAIN = "muziker.nl"
CATALOG = "https://www.muziker.nl/vinyl-lps"
UA = "VinylofyMuzikerCatalog/1.0 (https://vinylofy.com; contact: info@vinylofy.com)"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def price(value: str) -> str:
    match = re.search(r"[0-9][0-9.]*,[0-9]{1,2}|[0-9]+(?:\.[0-9]{1,2})?", value or "")
    if not match:
        raise ValueError("price_not_proven")
    raw = match.group(0).replace(".", "").replace(",", ".") if "," in match.group(0) else match.group(0)
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("invalid_price") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("nonpositive_price")
    return f"{amount:.2f}"


def artist_title(value: str) -> tuple[str, str]:
    parts = re.split(r"\s+[|–—-]\s+", " ".join(value.split()), maxsplit=1)
    if len(parts) != 2 or not all(parts):
        raise ValueError("artist_title_not_proven")
    return parts[0][:200], parts[1][:300]


def parse_page(body: str, source_url: str, observed_at: str, rejected: list | None = None) -> tuple[list[dict], str | None]:
    soup = BeautifulSoup(body, "html.parser")
    rows: list[dict] = []
    tiles = soup.select("div.product-tile")
    if not tiles:
        raise ValueError("catalog_page_has_no_product_tiles")
    for tile in tiles:
        link = tile.select_one("a.link-overlay[href]")
        heading = tile.select_one("h4.product-tile-header")
        subtype = tile.select_one("p.product-tile-sub-header")
        amount = tile.select_one(".tile-price .price")
        stock = tile.select_one(".stock-status")
        if not link or not heading or not subtype or not amount:
            continue
        if "lp" not in subtype.get_text(" ", strip=True).lower() and not re.search(r"\bvinyl\b", heading.get_text(" ", strip=True), re.I):
            continue
        title_raw = heading.get_text(" ", strip=True)
        listing_url = urljoin(CATALOG + "/", link["href"])
        approved_url(listing_url, DOMAIN)
        try:
            artist, title = artist_title(title_raw)
            listing_price = price(amount.get_text(" ", strip=True))
        except ValueError as exc:
            if rejected is not None:
                rejected.append({"url": listing_url, "title": title_raw, "reason": str(exc)})
            continue
        stock_text = stock.get_text(" ", strip=True) if stock else ""
        availability = ("out_of_stock" if re.search(r"uitverkocht|niet op voorraad", stock_text, re.I)
                        else "in_stock" if re.search(r"op voorraad", stock_text, re.I) else "unknown")
        rows.append({
            "source_product_id": tile.get("data-product-code") or str(uuid.uuid5(uuid.NAMESPACE_URL, listing_url)),
            "source_url": listing_url,
            "title_raw": title_raw,
            "artist": artist,
            "title": title,
            "price": listing_price,
            "currency": "EUR",
            "availability": availability,
            "observed_at": observed_at,
            "source_sha256": hashlib.sha256(body.encode()).hexdigest(),
        })
    next_link = soup.select_one("a.load-next-products[href], a.paginate-next-page[href]:not([href='#'])")
    next_url = urljoin(CATALOG + "/", next_link["href"]) if next_link else None
    if next_url:
        approved_url(next_url, DOMAIN)
    return rows, next_url


def write_rows(conn, rows: list[dict], run_id: str, next_url: str | None = None, page_signature: str | None = None) -> int:
    shop = conn.execute("select id from public.shops where is_active and regexp_replace(domain,'^www\\.','')=%s", (DOMAIN,)).fetchone()
    if not shop:
        # Registration is part of the explicit production setup; it does not
        # infer shipping eligibility or publish an alternative.
        conn.execute("""insert into public.shops(name,domain,country,is_active)
          values('Muziker',%s,'NL',true)
          on conflict(domain) do update set name=excluded.name,is_active=true
          returning id""", (DOMAIN,))
        shop = conn.execute("select id from public.shops where regexp_replace(domain,'^www\\.','')=%s", (DOMAIN,)).fetchone()
    if not shop:
        raise RuntimeError("muziker_shop_registration_failed")
    shop_id = shop[0]
    conn.execute("""insert into public.scrape_runs
      (id,shop_id,job_type,status,config) values(%s,%s,'catalog','running',%s)""",
      (run_id, shop_id, Jsonb({"source": DOMAIN, "route": CATALOG, "artist_title": True, "database_writes": True, "muziker_checkpoint_v1": True, "next_url": next_url, "page_signature": page_signature})))
    written = 0
    for row in rows:
        raw_id = uuid.uuid5(uuid.NAMESPACE_URL, f"muziker:{row['source_url']}:{row['observed_at'][:10]}")
        payload = {
            "artist": row["artist"], "title": row["title"], "format": "LP",
            "price_source": "listing", "listing_seen_at": row["observed_at"],
            "route": "ARTIST_TITLE", "ean_status": "EAN_NOT_FOUND",
            "condition_status": "new", "format_status": "vinyl",
            "source_sha256": row["source_sha256"], "status": "validated",
            "label": f"{row['artist']} {row['title']}",
        }
        with conn.transaction():
            cur = conn.execute("""insert into public.raw_shop_scrapes
              (id,run_id,shop_id,source_url,source_product_id,title_raw,ean_raw,price_raw,availability_raw,payload,scraped_at)
              values(%s,%s,%s,%s,%s,%s,null,%s,%s,%s,%s)
              on conflict(id) do update set price_raw=excluded.price_raw,
                availability_raw=excluded.availability_raw,payload=excluded.payload,scraped_at=excluded.scraped_at""",
              (raw_id, run_id, shop_id, row["source_url"], row["source_product_id"], row["title_raw"], row["price"], row["availability"], Jsonb(payload), row["observed_at"]))
            written += cur.rowcount
            conn.execute("""insert into public.album_offer_queue
              (shop_id,product_url,source_product_id,last_raw_id,source_input,status,next_attempt_at)
              values(%s,%s,%s,%s,%s,'pending_source',now())
              on conflict(shop_id,product_url) do update set last_raw_id=excluded.last_raw_id,
                source_input=excluded.source_input,status=case when album_offer_queue.status in ('published','ean_routed')
                  then album_offer_queue.status else 'pending_source' end,
                next_attempt_at=case when album_offer_queue.status in ('published','ean_routed')
                  then album_offer_queue.next_attempt_at else now() end,updated_at=now()""",
              (shop_id, row["source_url"], row["source_product_id"], raw_id, Jsonb({
                  "raw_shop_id": str(shop_id), "source_url": row["source_url"], "source_title": row["title_raw"],
                  "title_raw": row["title_raw"], "artist": row["artist"], "price": row["price"],
                  "currency": "EUR", "format": "LP", "price_source": "listing",
                  "listing_observed_at": row["observed_at"], "label": f"{row['artist']} {row['title']}",
              })))
    conn.execute("""update public.scrape_runs set status='completed',finished_at=now(),
      items_found=%s,items_processed=%s,items_success=%s,items_failed=0 where id=%s""",
      (len(rows), len(rows), written, run_id))
    return written


def read_checkpoint(conn) -> str:
    row = conn.execute("""select config->>'next_url' from public.scrape_runs
      where status='completed' and config->>'muziker_checkpoint_v1'='true'
      order by finished_at desc, id desc limit 1""").fetchone()
    url = row[0] if row and row[0] else CATALOG
    approved_url(url, DOMAIN)
    if urlsplit(url).path.rstrip('/') != urlsplit(CATALOG).path:
        raise ValueError('invalid_checkpoint_path')
    return url


def read_previous_signature(conn) -> str | None:
    row = conn.execute("""select case when config->>'next_url' is not null
      then config->>'page_signature' end from public.scrape_runs
      where status='completed' and config->>'muziker_checkpoint_v1'='true'
      order by finished_at desc, id desc limit 1""").fetchone()
    return row[0] if row else None


def run(max_pages: int, write: bool) -> dict:
    observed = now(); run_id = str(uuid.uuid4()); transport = Transport(DOMAIN)
    transport.session.headers["User-Agent"] = UA
    rows: list[dict] = []; rejected: list[dict] = []; seen: set[str] = set(); seen_products: set[str] = set()
    pages = 0; written = 0; duplicates = 0; previous_signature = None
    conn = None
    try:
        if write:
            conn = psycopg.connect(__import__("os").environ["DATABASE_URL"], prepare_threshold=None)
            url = read_checkpoint(conn)
            previous_signature = read_previous_signature(conn)
            conn.commit()
        else:
            url = CATALOG
        start_url = url
        transport.start(CATALOG)
        while url and pages < max_pages:
            if url in seen:
                raise RuntimeError("repeated_page")
            seen.add(url)
            page_rows, next_url = parse_page(transport.get(url), url, observed, rejected)
            urls = {r["source_url"] for r in page_rows}
            signature = hashlib.sha256("\n".join(sorted(urls)).encode()).hexdigest() if urls else None
            if signature and signature == previous_signature:
                raise RuntimeError("repeated_page_content")
            if next_url and next_url in seen:
                raise RuntimeError("repeated_page")
            unique_rows = []
            for row in page_rows:
                if row["source_url"] in seen_products:
                    duplicates += 1
                    continue
                seen_products.add(row["source_url"])
                unique_rows.append(row)
            # Persist the complete page and its signature atomically; a crash
            # cannot move the checkpoint past observations that were not saved.
            if conn:
                with conn.transaction():
                    written += write_rows(conn, unique_rows, str(uuid.uuid4()), next_url, signature)
            rows.extend(unique_rows); pages += 1; url = next_url; previous_signature = signature
        return {"shop": DOMAIN, "route": CATALOG, "run_id": run_id, "start_url": start_url,
                "pages": pages, "records": len(rows), "database_writes": bool(write), "complete": url is None,
                "next_url": url, "ean_records": 0, "artist_title_records": len(rows),
                "raw_written": written, "duplicate_products_skipped": duplicates, "rejected": rejected, "requests": transport.requests}
    finally:
        if conn:
            conn.close()
        transport.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("output/muziker/result.json"))
    args = parser.parse_args()
    if not 1 <= args.max_pages <= 100:
        parser.error("max-pages must be 1..100")
    result = run(args.max_pages, args.write)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
