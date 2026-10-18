#!/usr/bin/env python3
"""Listing-first, resumable scraper for Best Kept Records (WooCommerce)."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://bestkeptrecords.nl"
SHOP_URL = f"{BASE_URL}/winkel/"
DOMAIN = "bestkeptrecords.nl"
SHOP_NAME = "Best Kept Records"
MAX_DETAIL_BATCH = 250
DEFAULT_LISTING_WORKERS = 4
MAX_LISTING_WORKERS = 8
RESOLVED_DETAIL_STATUSES = {"ok", "missing_ean"}
LISTING_FIELDS = (
    "scraped_at", "source_shop", "product_key", "artist", "title", "format",
    "price", "standard_price", "currency", "is_sale", "availability",
    "product_url", "image_url", "page_found", "is_secondhand",
)
MASTER_FIELDS = LISTING_FIELDS + ("ean", "release_date", "label", "genre", "detail_status", "detail_error", "enriched_at")
EAN_RE = re.compile(r"\b(?:EAN(?:-13)?|EANCode|barcode)\s*[:#-]?\s*([0-9][0-9 .-]{7,17})", re.I)


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlsplit(urljoin(BASE_URL, value))
    if parsed.hostname not in {DOMAIN, f"www.{DOMAIN}"} or not parsed.path.rstrip("/").startswith("/product/"):
        return ""
    return urlunsplit(("https", DOMAIN, parsed.path.rstrip("/"), "", ""))


def parse_price(value: str | None) -> str:
    text = clean(value).replace("€", "").replace("EUR", "").replace(" ", "")
    match = re.search(r"\d{1,3}(?:\.\d{3})*,\d{1,2}|\d+(?:[.,]\d{1,2})?", text)
    if not match:
        return ""
    raw = match.group(0)
    raw = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    try:
        return f"{float(raw):.2f}"
    except ValueError:
        return ""


def extract_prices(card: Tag) -> tuple[str, str]:
    price = card.select_one(".price")
    if not price:
        return "", ""
    standard = parse_price(price.select_one("del, s").get_text(" ", strip=True) if price.select_one("del, s") else "")
    current_node = price.select_one("ins") or price
    amounts = [parse_price(node.get_text(" ", strip=True)) for node in current_node.select(".amount, .woocommerce-Price-amount")] or [parse_price(current_node.get_text(" ", strip=True))]
    current = next((item for item in reversed(amounts) if item), "")
    return current, standard if standard and current and float(standard) > float(current) else ""


def extract_artist_title(raw: str) -> tuple[str, str, str]:
    parts = [clean(part) for part in re.split(r"\s+[–—-]\s+", raw) if clean(part)]
    if len(parts) >= 3:
        return parts[-1], " – ".join(parts[1:-1]), parts[0]
    return "", clean(raw), ""


def extract_availability(card: Tag) -> str:
    container = card.find_parent("li") or card
    classes = " ".join(container.get("class", [])).casefold()
    text = clean(container.get_text(" ", strip=True)).casefold()
    if any(marker in classes or marker in text for marker in ("outofstock", "out-of-stock", "uitverkocht", "niet op voorraad")):
        return "out_of_stock"
    if "instock" in classes or card.select_one(".add_to_cart_button, .product_type_simple") or "in winkelwagen" in text:
        return "in_stock"
    return "unknown"


def parse_listing_page(html: str, page: int) -> tuple[list[dict[str, str]], str | None, set[str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    identities: set[str] = set()
    cards = soup.select("ul.products li.product, .products li.product")
    for card in cards:
        link = card.select_one("a.woocommerce-LoopProduct-link[href*='/product/'], a[href*='/product/']")
        product_url = normalize_url(link.get("href") if link else None)
        if not product_url or product_url in identities:
            continue
        title_node = card.select_one(".woocommerce-loop-product__title, .product-title")
        raw_title = clean(title_node.get_text(" ", strip=True) if title_node else "")
        if not raw_title:
            continue
        artist, title, format_label = extract_artist_title(raw_title)
        price, standard = extract_prices(card)
        if not price:
            continue
        image = card.select_one("img")
        identities.add(product_url)
        rows.append({
            "scraped_at": now_utc(), "source_shop": SHOP_NAME,
            "product_key": product_url.rstrip("/").rsplit("/", 1)[-1],
            "artist": artist, "title": title, "format": format_label,
            "price": price, "standard_price": standard, "currency": "EUR",
            "is_sale": "true" if standard else "false", "availability": extract_availability(card),
            "product_url": product_url,
            "image_url": clean(image.get("data-src") or image.get("data-lazy-src") or image.get("src") if image else ""),
            "page_found": str(page), "is_secondhand": "false",
        })
    next_node = soup.select_one("a.next.page-numbers, nav.woocommerce-pagination a.next, a[rel='next']")
    return rows, (normalize_url(next_node.get("href")) if next_node else None), identities


def listing_page_url(page: int) -> str:
    return SHOP_URL if page == 1 else f"{SHOP_URL}page/{page}/"


def extract_last_page(html: str) -> int | None:
    """Read the terminal numbered page from WooCommerce pagination metadata."""
    soup = BeautifulSoup(html, "html.parser")
    page_numbers: list[int] = []
    for node in soup.select("nav.woocommerce-pagination a[href], .woocommerce-pagination a[href], a.page-numbers[href]"):
        match = re.search(r"/winkel/page/(\d+)/?", node.get("href", ""))
        if match:
            page_numbers.append(int(match.group(1)))
    return max(page_numbers) if page_numbers else None


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, connect=3, read=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",), raise_on_status=False)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "VinylofyBestKeptRecords/1.0 (+https://vinylofy.com)", "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8"})
    return session


def fetch(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=30)
    if response.status_code == 429:
        raise RuntimeError(f"Best Kept Records rate limit reached: {url}")
    response.raise_for_status()
    return response.text


def _fetch_listing_page(page: int, delay: float) -> tuple[int, str | None]:
    """Fetch one listing page with a private session for thread safety."""
    if delay:
        time.sleep(delay)
    try:
        return page, fetch(build_session(), listing_page_url(page))
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return page, None
        raise


def scrape_listings(
    session: requests.Session,
    max_pages: int,
    delay: float,
    listing_workers: int = DEFAULT_LISTING_WORKERS,
) -> tuple[list[dict[str, str]], int]:
    if not 1 <= listing_workers <= MAX_LISTING_WORKERS:
        raise ValueError(f"listing_workers moet tussen 1 en {MAX_LISTING_WORKERS} liggen")

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    seen_page_sets: set[frozenset[str]] = set()

    # Page 1 provides the WooCommerce terminal-page metadata. Once that is
    # known, bounded parallelism reduces wall time without losing the
    # catalogue stop condition. If metadata is absent, retain sequential
    # pagination so an arbitrary page limit is never the only stop signal.
    try:
        first_html = fetch(session, listing_page_url(1))
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            print("[STOP] listing page 1 returned HTTP 404", flush=True)
            return [], 0
        raise

    page_results: dict[int, tuple[list[dict[str, str]], set[str]]] = {}
    first_rows, _next, first_identities = parse_listing_page(first_html, 1)
    page_results[1] = (first_rows, first_identities)
    last_page = extract_last_page(first_html)
    target_last_page = min(max_pages, last_page) if max_pages and last_page else (max_pages or last_page)

    if target_last_page and target_last_page >= 2 and listing_workers > 1:
        pages = range(2, target_last_page + 1)
        with ThreadPoolExecutor(max_workers=listing_workers) as executor:
            futures = [executor.submit(_fetch_listing_page, page, delay) for page in pages]
            for future in as_completed(futures):
                page, html = future.result()
                if html is None:
                    print(f"[STOP] listing page {page} returned HTTP 404", flush=True)
                    continue
                page_rows, _next, identities = parse_listing_page(html, page)
                page_results[page] = (page_rows, identities)
    else:
        page = 2
        fetched_page_sets = {frozenset(first_identities)}
        while target_last_page is None or page <= target_last_page:
            try:
                html = fetch(session, listing_page_url(page))
            except requests.HTTPError as exc:
                # Best Kept Records exposes no empty terminal page; it returns
                # 404 after the last numbered catalogue page.
                if exc.response is not None and exc.response.status_code == 404:
                    print(f"[STOP] listing page {page} returned HTTP 404", flush=True)
                    break
                raise
            page_rows, _next, identities = parse_listing_page(html, page)
            if not identities or frozenset(identities) in fetched_page_sets:
                print(f"[STOP] listing page {page} is empty or repeats a previous page", flush=True)
                break
            fetched_page_sets.add(frozenset(identities))
            page_results[page] = (page_rows, identities)
            if target_last_page is not None and page >= target_last_page:
                break
            page += 1
            if delay:
                time.sleep(delay)

    page = 1
    processed_pages = 0
    while page in page_results:
        page_rows, identities = page_results[page]
        if not identities or frozenset(identities) in seen_page_sets:
            break
        seen_page_sets.add(frozenset(identities))
        new_rows = [row for row in page_rows if row["product_url"] not in seen]
        if not new_rows:
            break
        rows.extend(new_rows)
        seen.update(row["product_url"] for row in new_rows)
        processed_pages = page
        print(f"[PAGE {page}] cards={len(identities)} products={len(rows)}", flush=True)
        if last_page is not None and page >= last_page:
            print(f"[STOP] reached terminal listing page {last_page}", flush=True)
            break
        page += 1
    return rows, processed_pages


def parse_detail_page(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main") or soup
    text = clean(main.get_text(" ", strip=True))
    eans = [re.sub(r"\D", "", match.group(1)) for match in EAN_RE.finditer(text)]
    eans = list(dict.fromkeys(ean for ean in eans if len(ean) in {8, 12, 13, 14}))
    def labeled(label: str) -> str:
        match = re.search(rf"{label}\s*:\s*([^|]+?)(?=\s+(?:Artist|Label|Genre|Release datum|EAN|Media Type|Availability|Units)\s*:|$)", text, re.I)
        return clean(match.group(1)) if match else ""
    media = labeled("Media Type")
    release = labeled("Release datum")
    secondhand = bool(soup.select_one("a[href*='/product-categorie/tweedehands/']"))
    image = soup.select_one("meta[property='og:image'], meta[name='og:image']")
    return {
        "ean": eans[0] if len(eans) == 1 else "", "release_date": release,
        "label": labeled("Label"), "genre": labeled("Genre"),
        "artist": labeled("Artist"), "format": media, "is_secondhand": "true" if secondhand else "false",
        "detail_status": "ok" if len(eans) == 1 else "missing_ean", "detail_error": "",
        "image_url": clean(image.get("content") if image else ""),
    }


def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError, TypeError):
        state = {}
    return {"version": 1, "cursor": int(state.get("cursor", 0) or 0), "details": state.get("details", {}) if isinstance(state.get("details", {}), dict) else {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def enrich_details(session: requests.Session, rows: list[dict[str, str]], state: dict, limit: int, delay: float, state_path: Path) -> int:
    if not rows or limit <= 0:
        return 0
    selected: list[dict[str, str]] = []
    cursor = state["cursor"] % len(rows)
    for offset in range(len(rows)):
        row = rows[(cursor + offset) % len(rows)]
        cached = state["details"].get(row["product_url"], {})
        if cached.get("detail_status") in RESOLVED_DETAIL_STATUSES:
            continue
        selected.append(row)
        if len(selected) >= limit:
            break
    for row in selected:
        try:
            details = parse_detail_page(fetch(session, row["product_url"]))
            row.update({key: value for key, value in details.items() if key not in {"price", "availability"}})
        except (requests.RequestException, RuntimeError) as exc:
            row.update({"ean": "", "detail_status": "technical_error", "detail_error": type(exc).__name__})
        row["enriched_at"] = now_utc()
        state["details"][row["product_url"]] = {key: row.get(key, "") for key in ("ean", "detail_status", "detail_error", "enriched_at", "artist", "format", "is_secondhand")}
        save_state(state_path, state)
        if delay:
            time.sleep(delay)
    if selected:
        state["cursor"] = (rows.index(selected[-1]) + 1) % len(rows)
    return len(selected)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MASTER_FIELDS, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Best Kept Records listing-first scraper")
    parser.add_argument("--max-pages", type=int, default=2, help="0 = volledige catalogus")
    parser.add_argument("--detail-limit", type=int, default=10, help="0..250 detailpagina's per run")
    parser.add_argument("--listing-workers", type=int, default=DEFAULT_LISTING_WORKERS, help=f"begrensde parallelle listingrequests (1..{MAX_LISTING_WORKERS})")
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/bestkeptrecords"))
    parser.add_argument("--detail-state-file", type=Path, default=None)
    args = parser.parse_args()
    if args.max_pages < 0 or not 0 <= args.detail_limit <= MAX_DETAIL_BATCH or not 1 <= args.listing_workers <= MAX_LISTING_WORKERS or args.delay_seconds < 0.5:
        raise SystemExit(f"max-pages >= 0, detail-limit 0..250, listing-workers 1..{MAX_LISTING_WORKERS} en delay-seconds >= 0.5 vereist")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.detail_state_file or args.output_dir / "bestkeptrecords_detail_state.json"
    session = build_session()
    rows, pages = scrape_listings(session, args.max_pages, args.delay_seconds, args.listing_workers)
    if not rows:
        raise SystemExit("Best Kept Records listing leverde geen producten op")
    state = load_state(state_path)
    for row in rows:
        cached = state["details"].get(row["product_url"], {})
        row.update({key: value for key, value in cached.items() if key in {"ean", "release_date", "label", "genre", "detail_status", "detail_error", "enriched_at", "is_secondhand"} and value})
        row.setdefault("detail_status", "not_sampled")
    attempted = enrich_details(session, rows, state, args.detail_limit, args.delay_seconds, state_path)
    write_csv(args.output_dir / "bestkeptrecords_products.csv", rows)
    summary = {"pages": pages, "products": len(rows), "detail_attempted": attempted, "detail_resolved": sum(row.get("detail_status") in RESOLVED_DETAIL_STATUSES for row in rows), "detail_pending": sum(row.get("detail_status") not in RESOLVED_DETAIL_STATUSES for row in rows)}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
