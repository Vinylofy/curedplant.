#!/usr/bin/env python3
"""Listing-first Vinyl Freaks scraper; browser transport without anti-bot evasion."""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.importers.common import strict_normalize_gtin

BASE_URL = "https://vinyl-freaks.nl"
CATEGORY_URL = BASE_URL + "/vinyl/nieuwe-lps/"
SHOP_NAME = "Vinyl Freaks"
LISTING_FIELDS = (
    "source_shop", "product_id", "product_key", "artist", "title", "format",
    "price", "standard_price", "is_sale", "currency", "availability",
    "product_url", "image_url", "page_found", "scraped_at",
)
DETAIL_FIELDS = (
    "ean", "ean_source", "catalogue_number", "discogs_release_id", "label",
    "detail_status", "detail_error", "detail_availability_observed",
    "cover_candidate_url", "enriched_at",
)
MASTER_FIELDS = LISTING_FIELDS + DETAIL_FIELDS


class BlockedError(RuntimeError):
    pass


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(value: object) -> str:
    raw = clean(value)
    if not raw:
        return ""
    parsed = urlsplit(urljoin(BASE_URL, raw))
    if parsed.scheme != "https" or parsed.hostname not in {"vinyl-freaks.nl", "www.vinyl-freaks.nl"}:
        return ""
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        return ""
    return BASE_URL + parsed.path.rstrip("/") + "/"


def barcode(value: object) -> str:
    # The shared helper strips letters. Never do that to a mixed catalogue field.
    raw = clean(value)
    if not re.fullmatch(r"(?:\d{8}|\d{12}|\d{13}|\d{14})", raw, flags=re.ASCII):
        return ""
    return raw if strict_normalize_gtin(raw) else ""


def money(value: str) -> str:
    raw = clean(value).replace("€", "").replace("EUR", "").replace(" ", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return ""
    return f"{amount:.2f}" if amount.is_finite() and amount > 0 else ""


def parse_listing_page(html: str, page: int) -> tuple[list[dict[str, str]], str | None, Counter]:
    soup = BeautifulSoup(html, "html.parser")
    rows, seen, skips = [], set(), Counter()
    for card in soup.select(".vf-card"):
        link = card.select_one(".vf-card__title-link[href]")
        url = normalize_url(link.get("href") if link else "")
        if not url or not urlsplit(url).path.startswith("/plaat/"):
            skips["invalid_product_url"] += 1
            continue
        if url in seen:
            skips["duplicate_url"] += 1
            continue
        title_node = card.select_one(".vf-card__title")
        artist_node = card.select_one(".vf-card__artist")
        artist = clean(artist_node.get_text(" ", strip=True)) if artist_node else ""
        # sr-only repeats the artist, so remove it from the title only.
        if title_node:
            for hidden in title_node.select(".sr-only"):
                hidden.decompose()
        title = clean(title_node.get_text(" ", strip=True)) if title_node else ""
        price_node = card.select_one(".vf-card__price")
        current = price_node.select_one("ins .amount") if price_node else None
        if current is None and price_node:
            current = next((n for n in price_node.select(".amount") if not n.find_parent("del")), None)
        regular = price_node.select_one("del .amount") if price_node else None
        price = money(current.get_text()) if current else ""
        standard = money(regular.get_text()) if regular else price
        if not title or not artist or not price:
            skips["missing_artist_title_or_price"] += 1
            continue
        action = card.select_one(".vf-card__add-btn")
        available = bool(action and not action.has_attr("disabled") and action.get("aria-disabled") != "true")
        classes = set(card.get("class", []))
        availability = "out_of_stock" if "outofstock" in classes else "in_stock" if available else "unknown"
        identity = card.select_one("[data-product-id], [data-product_id]")
        product_id = clean(identity.get("data-product-id") or identity.get("data-product_id")) if identity else ""
        image = card.select_one(".vf-card__img--front")
        rows.append({
            "source_shop": SHOP_NAME, "product_id": product_id,
            "product_key": "vinylfreaks:" + (product_id or url), "artist": artist,
            "title": title, "format": "Vinyl", "price": price,
            "standard_price": standard, "is_sale": str(bool(regular)).lower(),
            "currency": "EUR", "availability": availability, "product_url": url,
            "image_url": clean(image.get("src")) if image else "",
            "page_found": str(page), "scraped_at": now_iso(),
        })
        seen.add(url)
    nav = soup.select_one('nav[aria-label="Berichten paginering"]')
    next_node = nav.select_one("a.next") if nav else None
    if next_node is None and nav:
        next_node = next((a for a in nav.select("a[href]") if "volgende" in a.get_text().casefold()), None)
    next_url = normalize_url(next_node.get("href")) if next_node else ""
    if next_url and not re.fullmatch(r"/vinyl/nieuwe-lps/(?:page/\d+/)?", urlsplit(next_url).path):
        raise ValueError("Pagination escaped the new vinyl category")
    return rows, next_url or None, skips


def json_nodes(value):
    if isinstance(value, list):
        for child in value:
            yield from json_nodes(child)
    elif isinstance(value, dict):
        yield value
        yield from json_nodes(value.get("@graph", []))


def parse_detail_page(html: str, source_url: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    products = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        for node in json_nodes(data):
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if "Product" in types:
                product_url = normalize_url(node.get("url"))
                if source_url and product_url and product_url != normalize_url(source_url):
                    continue
                products.append(node)
    result = dict.fromkeys(DETAIL_FIELDS, "")
    result.update(detail_status="missing_ean", enriched_at=now_iso())
    codes: dict[str, tuple[str, str]] = {}
    invalid_explicit = False
    for product in products:
        for field in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14"):
            if field in product:
                code = barcode(product[field])
                if code:
                    codes[strict_normalize_gtin(code)] = (code, field)
                else:
                    invalid_explicit = True
        catalogue = clean(product.get("mpn"))
        result["catalogue_number"] = catalogue
        if catalogue:
            code = barcode(catalogue)
            if code:
                codes[strict_normalize_gtin(code)] = (code, "catalogue_number")
            else:
                result["detail_status"] = "invalid_catalogue_number"
        label = product.get("recordLabel", {})
        result["label"] = clean(label.get("name")) if isinstance(label, dict) else ""
        result["discogs_release_id"] = clean(product.get("sku"))
        image = product.get("image")
        if isinstance(image, str) and urlsplit(image).scheme == "https":
            result["cover_candidate_url"] = image
        offers = product.get("offers", {})
        if isinstance(offers, dict):
            result["detail_availability_observed"] = clean(offers.get("availability"))
    if len(codes) > 1 or invalid_explicit:
        result["detail_status"] = "ambiguous_or_invalid_gtin"
    elif len(codes) == 1:
        result["ean"], result["ean_source"] = next(iter(codes.values()))
        result["detail_status"] = "ok"
    return result


def detect_block(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one(".vf-card, script[type='application/ld+json']"):
        return False
    text = clean(soup.get_text()).casefold()
    return any(s in text for s in ("checking your browser", "javascript required", "verify you are human", "captcha", "access denied"))


class Client:
    def __init__(self, transport: str, delay: float, browser_channel: str = "chromium"):
        self.transport, self.delay, self.last = transport, delay, 0.0
        self.browser_channel = browser_channel
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Vinylofy-VinylFreaks/1.0"
        self.browser = self.runtime = self.page = None

    def __enter__(self):
        if self.transport == "browser":
            from playwright.sync_api import sync_playwright
            self.runtime = sync_playwright().start()
            try:
                options = {"headless": True}
                if self.browser_channel != "chromium":
                    options["channel"] = self.browser_channel
                self.browser = self.runtime.chromium.launch(**options)
                self.page = self.browser.new_page(user_agent="Vinylofy-VinylFreaks/1.0")
            except Exception:
                self.close()
                raise
        return self

    def close(self):
        self.session.close()
        if self.browser:
            self.browser.close()
        if self.runtime:
            self.runtime.stop()

    def __exit__(self, *args):
        self.close()

    def get(self, url: str) -> str:
        if normalize_url(url) != url:
            raise ValueError("Invalid source URL")
        for attempt in range(3):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            if self.page:
                response = self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                status = response.status if response else 0
                html = self.page.content()
                # Allow an ordinary browser's automatic JS check to settle; no challenge solving.
                if detect_block(html):
                    try:
                        self.page.wait_for_selector('.vf-card, script[type="application/ld+json"]', state="attached", timeout=15000)
                    except Exception:
                        pass
                    html = self.page.content()
                final_url = self.page.url
                retry_after = response.headers.get("retry-after", "") if response else ""
            else:
                response = self.session.get(url, timeout=30)
                status, html, final_url = response.status_code, response.text, response.url
                retry_after = response.headers.get("Retry-After", "")
            if normalize_url(final_url) != url or detect_block(html) or status in {401, 403}:
                raise BlockedError("Source blocked or redirected; stop without evasion")
            if status == 429 or 500 <= status < 600:
                if attempt == 2:
                    raise RuntimeError(f"HTTP {status} after bounded retries")
                if status == 429 and retry_after.isdigit() and int(retry_after) > 60:
                    raise RuntimeError("Rate limit requires a later run")
                time.sleep(max(2 ** (attempt + 1), int(retry_after) if retry_after.isdigit() else 0))
                continue
            if status < 200 or status >= 400:
                raise RuntimeError(f"HTTP {status}")
            return html
        raise RuntimeError("Fetch failed")


def scrape_listings(client, max_pages: int):
    rows, seen, visited, skips = [], set(), set(), Counter()
    url, page, reason = CATEGORY_URL, 1, "last_page"
    while url:
        if url in visited:
            reason = "repeated_page_url"
            break
        visited.add(url)
        found, next_url, page_skips = parse_listing_page(client.get(url), page)
        skips.update(page_skips)
        if not found:
            # An unexpected empty intermediate page must not silently replace a good snapshot.
            raise RuntimeError("Listing returned no valid products")
        new_rows = [r for r in found if r["product_url"] not in seen]
        if not new_rows:
            reason = "no_new_products"
            break
        rows.extend(new_rows)
        seen.update(r["product_url"] for r in new_rows)
        if not next_url:
            break
        if max_pages and page >= max_pages:
            reason = "page_limit"
            break
        url, page = next_url, page + 1
    return rows, {"pages": len(visited), "products": len(rows), "stop_reason": reason, "skips": dict(skips)}


def merge_details(rows, previous):
    by_key = {r["product_key"]: r for r in previous}
    for row in rows:
        old = by_key.get(row["product_key"], {})
        # A product ID must not carry enrichment to another URL/edition.
        if all(old.get(k) == row.get(k) for k in ("product_url", "artist", "title")):
            row.update({k: old.get(k, "") for k in DETAIL_FIELDS})
    return rows


def enrich_details(client, rows, limit: int):
    unresolved = [r for r in rows if not (barcode(r.get("ean")) and r.get("detail_status") == "ok")]
    # Unattempted rows first, then oldest failures. Missing EANs do not monopolize every run.
    unresolved.sort(key=lambda r: (r.get("enriched_at", ""), r["product_key"]))
    attempted = 0
    for row in unresolved[:limit]:
        attempted += 1
        try:
            details = parse_detail_page(client.get(row["product_url"]), row["product_url"])
        except BlockedError:
            raise
        except Exception as exc:
            details = {"detail_status": "technical_error", "detail_error": type(exc).__name__, "enriched_at": now_iso()}
        row.update(details)  # Parser contains detail fields only, never price/artist/availability.
    return attempted


def read_rows(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("listing", "detail", "both"), default="both")
    parser.add_argument("--transport", choices=("browser", "http"), default="browser")
    parser.add_argument("--browser-channel", choices=("chromium", "msedge", "chrome"), default="msedge" if sys.platform == "win32" else "chromium")
    parser.add_argument("--max-pages", type=int, default=1, help="0 = follow pagination to its stop condition")
    parser.add_argument("--detail-limit", type=int, default=5)
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/vinylfreaks"))
    args = parser.parse_args(argv)
    if args.max_pages < 0 or not 0 <= args.detail_limit <= 100 or not math.isfinite(args.delay_seconds) or args.delay_seconds < 1:
        parser.error("max-pages >= 0; detail-limit 0..100; finite delay-seconds >= 1 required")
    listing_path = args.output_dir / "vinylfreaks_listings.csv"
    master_path = args.output_dir / "vinylfreaks_master.csv"
    cache_path = args.output_dir / "vinylfreaks_detail_cache.csv"
    summary = {"mode": args.mode, "transport": args.transport, "detail_attempted": 0}
    rows = read_rows(master_path)
    cache = {r["product_key"]: r for r in read_rows(cache_path) or rows}
    try:
        with Client(args.transport, args.delay_seconds, args.browser_channel) as client:
            if args.mode in {"listing", "both"}:
                fresh, listing_summary = scrape_listings(client, args.max_pages)
                summary.update(listing_summary)
                rows = merge_details(fresh, cache.values())
                # Publish listing snapshot immediately. A failed detail run cannot erase fresh prices.
                write_rows(listing_path, rows, LISTING_FIELDS)
                write_rows(master_path, rows, MASTER_FIELDS)
            elif not rows:
                raise RuntimeError("No master snapshot available; run listing first")
            if args.mode in {"detail", "both"}:
                summary["detail_attempted"] = enrich_details(client, rows, args.detail_limit)
                write_rows(master_path, rows, MASTER_FIELDS)
    except Exception as exc:
        summary.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        # Keep partial successful enrichment for resume, but return failure to prevent import.
        if rows:
            write_rows(master_path, rows, MASTER_FIELDS)
    else:
        summary["status"] = "ok"
    summary.update(products=len(rows), ean_hits=sum(bool(barcode(r.get("ean"))) for r in rows))
    cache.update({r["product_key"]: r for r in rows})
    write_rows(cache_path, cache.values(), MASTER_FIELDS)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "scrape_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
