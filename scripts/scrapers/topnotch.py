#!/usr/bin/env python3
"""Listing-first Top Notch Shop scraper with resumable 100-item detail batches."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.topnotch-shop.nl"
LISTING_URL = f"{BASE_URL}/collections/vinyl"
DOMAIN = "topnotch-shop.nl"
SHOP_NAME = "Top Notch Shop"
MARKET_CURRENCY = "EUR"
DEFAULT_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT = 30
MAX_DETAIL_BATCH = 100
RESOLVED_DETAIL_STATUSES = {"ok", "missing_ean"}

LISTING_FIELDS = (
    "scraped_at", "source_shop", "product_id", "variant_id", "product_key",
    "artist", "title", "format", "price", "standard_price", "currency", "is_sale",
    "availability", "product_url", "image_url", "page_found",
)
MASTER_FIELDS = LISTING_FIELDS + ("ean", "detail_status", "detail_error", "enriched_at")
NON_VINYL_RE = re.compile(r"\b(?:CD|DVD|CASSETTE|DIGITAL|BLU[ -]?RAY)\b", re.I)
EAN_LABEL_RE = re.compile(r"(?:EAN(?:-13)?|GTIN(?:-\d{1,2})?|barcode|bar\s*code)\s*[:#-]?\s*([0-9][0-9 .-]{7,17})", re.I)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlsplit(urljoin(BASE_URL, value))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {DOMAIN, f"www.{DOMAIN}"}:
        return ""
    if not re.match(r"^/products/[^/]+/?$", parsed.path, re.I):
        return ""
    return urlunsplit(("https", DOMAIN, parsed.path.rstrip("/"), "", ""))


def normalize_image_url(value: str | None) -> str:
    if not value:
        return ""
    first = clean(value).split(",", 1)[0].split(" ", 1)[0]
    parsed = urlsplit(urljoin(BASE_URL, first))
    if parsed.hostname not in {DOMAIN, f"www.{DOMAIN}"}:
        return ""
    return urlunsplit(("https", DOMAIN, parsed.path, parsed.query, ""))


def parse_money(value: str | None) -> str:
    text = clean(value).replace("€", "").replace("EUR", "")
    match = re.search(r"\d{1,3}(?:\.\d{3})*,\d{1,2}|\d+(?:[.,]\d{1,2})?", text)
    if not match:
        return ""
    raw = match.group(0).replace(".", "").replace(",", ".") if "," in match.group(0) else match.group(0)
    try:
        amount = float(raw)
    except ValueError:
        return ""
    return f"{amount:.2f}" if amount > 0 else ""


def extract_prices(card: Tag) -> tuple[str, str]:
    price = card.select_one(".card__price")
    if price is None:
        return "", ""
    current_node = price.select_one(".price__current")
    current = parse_money(current_node.get_text(" ", strip=True) if current_node else "")
    compare_node = price.select_one(".price__compare")
    standard = parse_money(compare_node.get_text(" ", strip=True) if compare_node else "")
    return current, standard if standard and current and float(standard) > float(current) else ""


def extract_availability(card: Tag) -> str:
    """Use explicit add-to-cart/reminder evidence; never infer from price alone."""
    card_text = clean(card.get_text(" ", strip=True)).casefold()
    if "uitverkocht" in card_text or "sold out" in card_text or "out of stock" in card_text:
        return "out_of_stock"
    form = card.select_one("product-form") or card.select_one("form[data-type='add-to-cart-form']")
    if form is None:
        return "unknown"
    button = form.select_one("button[name='add'], button[type='submit']")
    if button is not None:
        label = clean(button.get_text(" ", strip=True)).casefold()
        disabled = button.has_attr("disabled") or button.get("aria-disabled") == "true"
        if not disabled and ("winkelmandje" in label or "add to cart" in label):
            return "in_stock"
    if form.select_one("a[aria-label*='Herinner mij'], a[aria-label*='Notify']") is not None:
        return "out_of_stock"
    if "herinner mij" in clean(form.get_text(" ", strip=True)).casefold():
        return "out_of_stock"
    return "unknown"


def _product_url(card: Tag) -> str:
    for node in card.select("a[href^='/products/']"):
        url = normalize_url(node.get("href"))
        if url:
            return url
    return ""


def _first_text(card: Tag, selector: str) -> str:
    node = card.select_one(selector)
    return clean(node.get_text(" ", strip=True)) if node else ""


def parse_listing_page(html: str, page: int) -> tuple[list[dict[str, str]], str | None, set[str], Counter[str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    identities: set[str] = set()
    skips: Counter[str] = Counter()
    for card in soup.select(".product_card"):
        product_id = clean(card.get("data-product"))
        form = card.select_one("product-form")
        variant_id = clean(form.get("data-variant") if form else "")
        identity = f"{product_id}:{variant_id}" if product_id and variant_id else ""
        if not identity:
            skips["missing_product_or_variant_id"] += 1
            continue
        if identity in identities:
            skips["duplicate_product_variant_on_page"] += 1
            continue
        identities.add(identity)
        product_url = _product_url(card)
        artist = _first_text(card, ".card__artist")
        title = _first_text(card, ".card__title")
        if NON_VINYL_RE.search(title):
            skips["non_vinyl"] += 1
            continue
        price, standard_price = extract_prices(card)
        if not product_url:
            skips["missing_product_url"] += 1
            continue
        if not artist:
            skips["missing_artist"] += 1
        if not title:
            skips["missing_title"] += 1
            continue
        if not price:
            skips["missing_listing_price"] += 1
            continue
        image = card.select_one(".card__image img")
        image_url = normalize_image_url(image.get("src") if image else "")
        rows.append({
            "scraped_at": now_utc_iso(), "source_shop": SHOP_NAME,
            "product_id": product_id, "variant_id": variant_id,
            "product_key": f"topnotch:{product_id}:{variant_id}",
            "artist": artist, "title": title, "format": "Vinyl",
            "price": price, "standard_price": standard_price, "currency": MARKET_CURRENCY,
            "is_sale": "true" if standard_price else "false",
            "availability": extract_availability(card), "product_url": product_url,
            "image_url": image_url, "page_found": str(page),
        })
    next_node = soup.select_one("a[rel='next']")
    next_url = normalize_url(next_node.get("href")) if next_node else None
    return rows, next_url, identities, skips


def listing_page_url(page: int) -> str:
    return LISTING_URL if page == 1 else f"{LISTING_URL}?page={page}"


class TopNotchClient:
    def __init__(self, session: requests.Session, delay_seconds: float = DEFAULT_DELAY_SECONDS):
        if delay_seconds < 0.5:
            raise ValueError("delay_seconds must be >= 0.5")
        self.session, self.delay_seconds, self.last_request_at = session, delay_seconds, None

    def get(self, url: str) -> str:
        if self.last_request_at is not None:
            remaining = self.delay_seconds - (time.monotonic() - self.last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        for attempt in range(3):
            self.last_request_at = time.monotonic()
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            except requests.RequestException:
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise
            if response.status_code == 429:
                raise RuntimeError(f"Top Notch rate limit reached (HTTP 429): {url}")
            if response.status_code in {500, 502, 503, 504} and attempt < 2:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.text
        raise RuntimeError(f"Top Notch transient HTTP failure: {url}")


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "VinylofyTopNotch/1.0 (+https://vinylofy.com)",
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    })
    return session


def scrape_listings(client: TopNotchClient, max_pages: int = 0) -> tuple[list[dict[str, str]], Counter[str], int]:
    if max_pages < 0:
        raise ValueError("max_pages must be >= 0")
    rows: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    seen_page_sets: set[frozenset[str]] = set()
    skips: Counter[str] = Counter()
    page = 1
    pages = 0
    while max_pages == 0 or page <= max_pages:
        html = client.get(listing_page_url(page))
        page_rows, next_url, page_ids, page_skips = parse_listing_page(html, page)
        skips.update(page_skips)
        if not page_ids:
            skips["empty_product_page"] += 1
            break
        page_set = frozenset(page_ids)
        if page_set in seen_page_sets:
            skips["repeated_product_variant_set"] += 1
            break
        seen_page_sets.add(page_set)
        pages += 1
        for row in page_rows:
            if row["product_key"] in seen_keys:
                skips["duplicate_product_variant_between_pages"] += 1
            else:
                seen_keys.add(row["product_key"])
                rows.append(row)
        print(f"[PAGE {page}] cards={len(page_ids)} accepted={len(page_rows)} total={len(rows)}", flush=True)
        if max_pages and page >= max_pages:
            break
        # Shopify themes may omit rel=next. The next numbered page is fetched;
        # empty/repeated-page checks are the stop conditions.
        page += 1 if next_url is not None or max_pages == 0 else 1
    return rows, skips, pages


def _detail_ean_candidates(soup: BeautifulSoup) -> list[str]:
    candidates: list[str] = []
    main = soup.select_one("main") or soup
    primary_upc = main.select_one("product-form [name='gtm_item_upc']")
    if primary_upc is not None:
        value = primary_upc.get("value") or primary_upc.get_text(" ", strip=True)
        if value:
            return [value]
    for node in main.select("[name='gtm_item_upc'], [itemprop^='gtin']"):
        value = node.get("value") or node.get("content") or node.get_text(" ", strip=True)
        if value:
            candidates.append(value)
    for script in main.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        objects = payload if isinstance(payload, list) else [payload]
        for obj in objects:
            if isinstance(obj, dict):
                for key in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "productID", "sku"):
                    if obj.get(key):
                        candidates.append(str(obj[key]))
    text = clean(main.get_text(" ", strip=True))
    candidates.extend(match.group(1) for match in EAN_LABEL_RE.finditer(text))
    return candidates


def _valid_ean(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits if len(digits) in {8, 12, 13, 14} else ""


def parse_detail_page(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    values = [_valid_ean(candidate) for candidate in _detail_ean_candidates(soup)]
    values = list(dict.fromkeys(value for value in values if value))
    ean = values[0] if len(values) == 1 else ""
    return {"ean": ean, "detail_status": "ok" if ean else "missing_ean", "detail_error": ""}


def load_detail_state(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "cursor": 0, "details": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"version": 1, "cursor": 0, "details": {}}
    if not isinstance(state, dict) or not isinstance(state.get("details"), dict):
        return {"version": 1, "cursor": 0, "details": {}}
    return {"version": 1, "cursor": int(state.get("cursor", 0) or 0), "details": state["details"]}


def save_detail_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def select_detail_rows(rows: list[dict[str, str]], state: dict, limit: int) -> list[dict[str, str]]:
    if limit <= 0 or not rows:
        return []
    cursor = int(state.get("cursor", 0) or 0) % len(rows)
    selected: list[dict[str, str]] = []
    last_index = cursor
    for offset in range(len(rows)):
        index = (cursor + offset) % len(rows)
        row = rows[index]
        cached = state["details"].get(row["product_url"], {})
        if cached.get("detail_status") in RESOLVED_DETAIL_STATUSES:
            continue
        selected.append(row)
        last_index = index
        if len(selected) >= limit:
            state["cursor"] = (last_index + 1) % len(rows)
            break
    else:
        if selected:
            state["cursor"] = (last_index + 1) % len(rows)
    return selected


def apply_cached_details(rows: list[dict[str, str]], state: dict) -> None:
    for row in rows:
        cached = state["details"].get(row["product_url"], {})
        row.update({
            "ean": cached.get("ean", ""),
            "detail_status": cached.get("detail_status", "not_sampled"),
            "detail_error": cached.get("detail_error", ""),
            "enriched_at": cached.get("enriched_at", ""),
        })


def scrape(*, max_pages: int, detail_limit: int, delay_seconds: float, detail_state_file: Path) -> tuple[list[dict[str, str]], dict]:
    if not 0 <= detail_limit <= MAX_DETAIL_BATCH:
        raise ValueError(f"detail_limit must be between 0 and {MAX_DETAIL_BATCH}")
    client = TopNotchClient(build_session(), delay_seconds)
    rows, skips, pages = scrape_listings(client, max_pages)
    state = load_detail_state(detail_state_file)
    apply_cached_details(rows, state)
    detail_rows = select_detail_rows(rows, state, detail_limit)
    for row in detail_rows:
        try:
            row.update(parse_detail_page(client.get(row["product_url"])))
        except (requests.RequestException, RuntimeError) as exc:
            row.update({"ean": "", "detail_status": "technical_error", "detail_error": type(exc).__name__})
        row["enriched_at"] = now_utc_iso()
        state["details"][row["product_url"]] = {
            "ean": row["ean"], "detail_status": row["detail_status"],
            "detail_error": row["detail_error"], "enriched_at": row["enriched_at"],
        }
        save_detail_state(detail_state_file, state)
    apply_cached_details(rows, state)
    resolved = sum(row["detail_status"] in RESOLVED_DETAIL_STATUSES for row in rows)
    return rows, {
        "pages": pages, "products": len(rows), "detail_attempted": len(detail_rows),
        "detail_cached_resolved": resolved, "detail_pending": len(rows) - resolved,
        "skips": dict(skips),
    }


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MASTER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Top Notch Shop listing/detail scraper")
    parser.add_argument("--max-pages", type=int, default=0, help="0 follows pagination until an empty/repeated page")
    parser.add_argument("--detail-limit", type=int, default=100, help="detail pages per run, maximum 100")
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/topnotch"))
    parser.add_argument("--detail-state-file", type=Path, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_pages < 0 or not 0 <= args.detail_limit <= MAX_DETAIL_BATCH or args.delay_seconds < 0.5:
        raise SystemExit("max-pages >= 0, detail-limit 0..100 and delay-seconds >= 0.5 required")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_file = args.detail_state_file or args.output_dir / "topnotch_detail_state.json"
    rows, summary = scrape(max_pages=args.max_pages, detail_limit=args.detail_limit,
                           delay_seconds=args.delay_seconds, detail_state_file=state_file)
    write_rows(args.output_dir / "topnotch_products.csv", rows)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
