#!/usr/bin/env python3
"""Bounded Discords.nl new-LP scraper using public Shopify JSON endpoints."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scripts.importers.common import strict_normalize_gtin

SHOP_ID = "discords"
SHOP_NAME = "Discords"
SHOP_DOMAIN = "discords.nl"
SHOP_COUNTRY = "NL"
BASE_URL = "https://discords.nl"
COLLECTION_HANDLE = "lps-nieuw"
PAGE_SIZE = 100
OUTPUT_COLUMNS = (
    "product_url", "product_id", "handle", "variant_id", "ean", "artist",
    "title", "format", "price", "compare_at_price", "currency",
    "availability", "image_url", "scraped_at",
)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=8, connect=5, read=5, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; Vinylofy-USF/1.0; +https://www.vinylofy.com)",
        "Accept": "application/json",
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    })
    return session


def collection_url(page: int, limit: int = PAGE_SIZE) -> str:
    return f"{BASE_URL}/collections/{COLLECTION_HANDLE}/products.json?limit={limit}&page={page}"


def product_url(handle: object) -> str:
    value = clean(handle).strip("/")
    return f"{BASE_URL}/products/{value}" if value and "/" not in value else ""


def product_json_url(source_url: str) -> str:
    return source_url.rstrip("/") + ".js"


def is_new_vinyl_product(product: dict[str, Any]) -> bool:
    product_type = clean(product.get("product_type") or product.get("type")).casefold()
    tags = product.get("tags") or []
    if isinstance(tags, str):
        tags = tags.split(",")
    haystack = " ".join([clean(product.get("title")), *(clean(tag) for tag in tags)]).casefold()
    if product_type != "lp":
        return False
    return not re.search(r"\b(?:used|second[ -]?hand|tweedehands)\b", haystack)


def split_artist_title(product: dict[str, Any]) -> tuple[str, str]:
    artist = clean(product.get("vendor"))
    raw_title = clean(product.get("title"))
    title = raw_title
    if artist:
        title = re.sub(rf"^{re.escape(artist)}\s*[-–—:]\s*", "", title, flags=re.I)
    title = re.sub(r"\s*\((?:\d+\s*[xX]\s*)?LPs?\)\s*$", "", title, flags=re.I).strip()
    if not artist:
        for separator in (" - ", " – ", " — "):
            if separator in title:
                artist, title = (clean(part) for part in title.split(separator, 1))
                break
    return artist, title


def selected_variant(product: dict[str, Any]) -> dict[str, Any] | None:
    variants = [row for row in (product.get("variants") or []) if isinstance(row, dict)]
    priced = [row for row in variants if clean(row.get("price"))]
    available = [row for row in priced if row.get("available") is True]
    candidates = available or priced
    if not candidates:
        return None
    return min(candidates, key=lambda row: float(row["price"]))


def listing_record(product: dict[str, Any], *, page: int, seen_at: datetime) -> dict[str, Any] | None:
    if not is_new_vinyl_product(product):
        return None
    url = product_url(product.get("handle"))
    variant = selected_variant(product)
    if not url or variant is None:
        return None
    artist, title = split_artist_title(product)
    images = product.get("images") or []
    first_image = images[0] if images else None
    image_url = clean(first_image.get("src") if isinstance(first_image, dict) else first_image)
    compare_at = clean(variant.get("compare_at_price"))
    price = clean(variant.get("price"))
    if compare_at:
        try:
            if float(compare_at) <= float(price):
                compare_at = ""
        except ValueError:
            compare_at = ""
    return {
        "product_url": url,
        "product_id": clean(product.get("id")),
        "handle": clean(product.get("handle")),
        "variant_id": clean(variant.get("id")),
        "ean": "",
        "artist": artist,
        "title": title,
        "format": "LP",
        "price": price,
        "compare_at_price": compare_at,
        "currency": "EUR",
        "availability": "in_stock" if variant.get("available") is True else "out_of_stock",
        "image_url": image_url,
        "scraped_at": seen_at.isoformat(),
        "collection_page": page,
        "source": "discords_collection_products_json",
    }


def detail_record(payload: dict[str, Any], listing: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("id")) != str(listing.get("product_id")):
        raise ValueError("Discords detail product identity mismatch")
    if not is_new_vinyl_product(payload):
        raise ValueError("Discords detail is not a new LP")
    variants = [row for row in (payload.get("variants") or []) if isinstance(row, dict)]
    expected_variant = str(listing.get("variant_id") or "")
    if expected_variant:
        selected = [row for row in variants if str(row.get("id")) == expected_variant]
        if len(selected) != 1:
            raise ValueError("Discords listing variant is absent from product detail")
        variants = selected
    codes = {strict_normalize_gtin(row.get("barcode")) for row in variants} - {None}
    ean = next(iter(codes)) if len(codes) == 1 else None
    artist, title = split_artist_title(payload)
    images = payload.get("images") or []
    first_image = images[0] if images else payload.get("featured_image")
    if isinstance(first_image, dict):
        first_image = first_image.get("src")
    image_url = clean(first_image)
    if image_url.startswith("//"):
        image_url = "https:" + image_url
    return {
        **listing,
        "ean": ean or "",
        "artist": artist or listing.get("artist", ""),
        "title": title or listing.get("title", ""),
        "image_url": image_url or listing.get("image_url", ""),
        "detail_issue": "" if ean else "missing_or_ambiguous_variant_gtin",
    }


def fetch_page(session: requests.Session, page: int, limit: int = PAGE_SIZE) -> list[dict[str, Any]]:
    response = session.get(collection_url(page, limit), timeout=(10, 30))
    response.raise_for_status()
    payload = response.json()
    products = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(products, list):
        raise ValueError("Discords collection response has no products list")
    return [row for row in products if isinstance(row, dict)]


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=1, help="0 = until empty/partial page")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--max-details", type=int, default=20)
    parser.add_argument("--output", default="data/raw/discords/discords_products.csv")
    args = parser.parse_args()
    if args.max_pages < 0 or not 1 <= args.page_size <= PAGE_SIZE or args.delay < 0 or args.max_details < 0:
        parser.error("invalid bounded scraper arguments")
    session, seen_at = make_session(), datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    page = 1
    try:
        while args.max_pages == 0 or page <= args.max_pages:
            products = fetch_page(session, page, args.page_size)
            if not products:
                break
            page_records = [row for product in products if (row := listing_record(product, page=page, seen_at=seen_at))]
            urls = {row["product_url"] for row in page_records}
            if not urls or urls.issubset(seen):
                break
            for row in page_records:
                if row["product_url"] not in seen:
                    records.append(row)
                    seen.add(row["product_url"])
            if len(products) < args.page_size:
                break
            page += 1
            time.sleep(args.delay)
        if args.details:
            for row in records[: args.max_details]:
                response = session.get(product_json_url(row["product_url"]), timeout=(10, 30))
                response.raise_for_status()
                row.update(detail_record(response.json(), row))
                time.sleep(args.delay)
    finally:
        session.close()
    write_csv(Path(args.output), records)
    print(json.dumps({"shop": SHOP_ID, "records": len(records), "details": min(len(records), args.max_details) if args.details else 0,
                      "valid_eans": sum(bool(row.get("ean")) for row in records), "output": args.output}))
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
