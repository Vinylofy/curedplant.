"""Run legacy listing/detail scrapers and their registered DB importer.

The scraper still produces its normal CSV checkpoint, while the importer is
the only component allowed to write to the shared database.  This keeps a
manual dry-run safe and makes the write boundary explicit.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import os
import subprocess
import sys
from pathlib import Path

import psycopg
from scripts.importers.common import parse_price


PROFILES = {
    "atthemovies": ("scripts.scrapers.atthemovies", "scripts.importers.import_atthemovies", "single"),
    "bestkeptrecords": ("scripts.scrapers.bestkeptrecords", "scripts.importers.import_bestkeptrecords", "legacy"),
    "blackvinyl": ("scripts.scrapers.blackvinyl", "scripts.importers.import_blackvinyl", "blackvinyl"),
    "getbackmusic": ("scripts.scrapers.getbackmusic", "scripts.importers.import_getbackmusic", "mode"),
    "grooverecords": ("scripts.scrapers.grooverecords", "scripts.importers.import_grooverecords", "mode"),
    "rockinoutrecords": ("scripts.scrapers.rockinoutrecords", "scripts.importers.import_rockinoutrecords", "legacy"),
    "suburban": ("scripts.scrapers.suburban", "scripts.importers.import_suburban", "mode"),
    "topnotch": ("scripts.scrapers.topnotch", "scripts.importers.import_topnotch", "legacy"),
    "vinyleers": ("scripts.scrapers.vinyleers", "scripts.importers.import_vinyleers", "legacy"),
    "vinylfreaks": ("scripts.scrapers.vinylfreaks", "scripts.importers.import_vinylfreaks", "mode"),
    "viprecords": ("scripts.scrapers.viprecords", "scripts.importers.import_viprecords", "mode"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=sorted(PROFILES), required=True)
    parser.add_argument("--lane", choices=("price", "detail"), required=True)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    scraper, importer, style = PROFILES[args.worker]
    if args.limit < 1:
        parser.error("--limit must be >= 1")

    detail_limit = str(args.limit if args.lane == "detail" else 0)
    if style == "mode":
        mode = "both" if args.lane == "detail" and args.worker in {"getbackmusic", "suburban", "viprecords"} else ("detail" if args.lane == "detail" else "listing")
        scraper_args = ["--mode", mode, "--max-pages", "1" if args.lane == "detail" else str(args.limit), "--detail-limit", detail_limit]
        if args.worker == "vinylfreaks":
            scraper_args.extend(["--transport", "http"])
    elif style == "blackvinyl":
        scraper_args = ["--detail-mode", "all" if args.lane == "detail" else "none", "--output", "data/raw/blackvinyl/blackvinyl_products.csv"]
    elif style == "legacy":
        scraper_args = ["--max-pages", "1" if args.lane == "detail" else str(args.limit), "--detail-limit", detail_limit]
    else:
        scraper_args = ["--max-pages", "1" if args.lane == "detail" else str(args.limit), "--detail-limit", detail_limit]
    scrape = [sys.executable, "-u", "-m", scraper, *scraper_args]
    print("[CUREDPLANT] legacy scrape:", " ".join(scrape), flush=True)
    result = subprocess.run(scrape, check=False)
    if result.returncode:
        return result.returncode

    if args.lane == "price":
        return sync_listing_prices(args.worker, write=args.write)

    import_command = [sys.executable, "-u", "-m", importer]
    if not args.write:
        import_command.append("--dry-run")
    print("[CUREDPLANT] importer:", " ".join(import_command), flush=True)
    return subprocess.run(import_command, check=False).returncode


def sync_listing_prices(worker: str, *, write: bool) -> int:
    """Update existing prices by shop/product URL without requiring an EAN."""
    _, importer, _ = PROFILES[worker]
    definition = importlib.import_module(importer).SHOP_DEFINITION
    csv_path = Path(definition.files.csv_output_path)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig", newline="")))
    valid = [row for row in rows if row.get("product_url") and row.get("price")]
    if not write:
        print(f"[PRICE DRY-RUN] rows={len(rows)} price_candidates={len(valid)}", flush=True)
        return 0
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required when write=true")
    updated = 0
    unmatched = 0
    with psycopg.connect(database_url, prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            cur.execute("select id from public.shops where domain = %s limit 1", (definition.config.shop_domain,))
            shop = cur.fetchone()
            if shop is None:
                raise SystemExit(f"Shop is not registered: {definition.config.shop_domain}")
            shop_id = str(shop[0])
            for row in valid:
                price = parse_price(row.get("price"))
                if price is None or price <= 0:
                    continue
                cur.execute(
                    """
                    update public.prices
                    set price = %s, currency = %s, availability = %s,
                        last_seen_at = now(), updated_at = now(), is_active = true
                    where shop_id = %s and product_url = %s
                    """,
                    (price, row.get("currency") or definition.config.currency, row.get("availability") or "unknown", shop_id, row["product_url"]),
                )
                if cur.rowcount:
                    updated += cur.rowcount
                else:
                    unmatched += 1
    print(f"[PRICE WRITE] updated={updated} unmatched={unmatched} candidates={len(valid)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
