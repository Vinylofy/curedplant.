#!/usr/bin/env python3
"""Listing-first, EAN-gated scraper for the new vinyl catalogue at Vinyleers."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://vinyleers.com"
LISTING_URL = f"{BASE_URL}/a/search/all?sort_by=created-descending&filter_type=lps&filter_hoesconditie=Mint+%28M%29"
DOMAIN = "vinyleers.com"
SHOP_NAME = "Vinyleers"
MARKET_CURRENCY = "EUR"
DEFAULT_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT = 30
MAX_DETAIL_BATCH = 500
SAMPLE_CHECK_LIMIT = 5
RESOLVED_DETAIL_STATUSES = {"ok", "missing_ean"}

LISTING_FIELDS = (
    "scraped_at", "source_shop", "product_id", "variant_id", "product_key",
    "artist", "title", "format", "price", "standard_price", "currency", "is_sale",
    "availability", "product_url", "image_url", "page_found", "new_badge",
    "is_secondhand",
)
MASTER_FIELDS = LISTING_FIELDS + (
    "ean", "detail_price", "price_match", "new_evidence", "detail_status",
    "detail_error", "enriched_at",
)
EAN_LABEL_RE = re.compile(
    r"(?:EAN(?:-13)?|GTIN(?:-\d{1,2})?|barcode|bar\s*code)\s*[:#-]?\s*([0-9][0-9 .-]{7,17})",
    re.I,
)
PRODUCT_BARCODE_RE = re.compile(r"[\"']barcode[\"']\s*:\s*[\"']([^\"']+)", re.I)
PRODUCT_PRICE_RE = re.compile(r"[\"']price[\"']\s*:\s*\{\s*[\"']amount[\"']\s*:\s*([0-9]+(?:\.[0-9]+)?)", re.I)
PRODUCT_AVAILABLE_RE = re.compile(r"[\"']available[\"']\s*:\s*(true|false)", re.I)


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
    first = clean(value).split(",", 1)[0].split(" ", 1)[0].replace("{width}", "1024")
    parsed = urlsplit(urljoin(BASE_URL, first))
    if parsed.hostname not in {DOMAIN, f"www.{DOMAIN}"}:
        return ""
    return urlunsplit(("https", DOMAIN, parsed.path, parsed.query, ""))


def parse_money(value: str | None) -> str:
    text = clean(value).replace("€", "").replace("EUR", "")
    match = re.search(r"\d{1,3}(?:\.\d{3})*,\d{1,2}|\d+(?:[.,]\d{1,2})?", text)
    if not match:
        return ""
    raw = match.group(0)
    raw = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    try:
        amount = float(raw)
    except ValueError:
        return ""
    return f"{amount:.2f}" if amount > 0 else ""


def _first_text(node: Tag, selector: str) -> str:
    selected = node.select_one(selector)
    return clean(selected.get_text(" ", strip=True)) if selected else ""


def _artist_title(raw: str) -> tuple[str, str]:
    value = clean(raw)
    if " - " not in value:
        return "", value
    artist, title = value.split(" - ", 1)
    return clean(artist), clean(title)


def extract_prices(card: Tag) -> tuple[str, str]:
    price = card.select_one(".caption .price, .price")
    if not price:
        return "", ""
    values = [parse_money(node.get_text(" ", strip=True)) for node in price.select(".theme-money")]
    values = [value for value in values if value]
    if not values:
        return "", ""
    current = values[0]
    standard = values[1] if len(values) > 1 and float(values[1]) > float(current) else ""
    return current, standard


def extract_availability(card: Tag) -> str:
    text = clean(card.get_text(" ", strip=True)).casefold()
    if any(marker in text for marker in ("uitverkocht", "sold out", "out of stock")):
        return "out_of_stock"
    button = card.select_one("form.vl-atc-form button, form[data-vl-atc-form] button")
    if button is not None:
        label = clean(button.get_text(" ", strip=True)).casefold()
        if not button.has_attr("disabled") and "winkelmandje" in label:
            return "in_stock"
    return "unknown"


def listing_page_url(page: int) -> str:
    if page == 1:
        return LISTING_URL
    query = dict(parse_qsl(urlsplit(LISTING_URL).query, keep_blank_values=True))
    query["page"] = str(page)
    return f"{BASE_URL}/a/search/all?{urlencode(query)}"


def extract_last_page(html: str) -> int | None:
    soup = BeautifulSoup(html, "html.parser")
    pages = []
    for node in soup.select(".pagination a[href]"):
        match = re.search(r"[?&]page=(\d+)", node.get("href", ""))
        if match:
            pages.append(int(match.group(1)))
    return max(pages) if pages else None


def parse_listing_page(html: str, page: int) -> tuple[list[dict[str, str]], str | None, set[str], Counter[str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    identities: set[str] = set()
    skips: Counter[str] = Counter()
    for card in soup.select(".product-block"):
        link = card.select_one("a[href^='/products/']")
        product_url = normalize_url(link.get("href") if link else None)
        form = card.select_one("form.vl-atc-form, form[data-vl-atc-form]")
        variant_id = clean(form.select_one("input[name='id']").get("value") if form and form.select_one("input[name='id']") else "")
        if not product_url or not variant_id:
            skips["missing_product_or_variant"] += 1
            continue
        product_id = clean(card.get("data-product-id") or "")
        identity = f"{product_url}:{variant_id}"
        if identity in identities:
            skips["duplicate_product_variant_on_page"] += 1
            continue
        identities.add(identity)
        title_raw = _first_text(card, ".caption .title") or clean(link.get("aria-label") if link else "")
        artist, title = _artist_title(title_raw)
        price, standard_price = extract_prices(card)
        new_badge = "nieuw" in clean(card.select_one(".corner-ribbon").get_text(" ", strip=True) if card.select_one(".corner-ribbon") else "").casefold()
        if not new_badge:
            skips["not_explicitly_new"] += 1
            continue
        if not title or not price:
            skips["missing_title_or_price"] += 1
            continue
        image = card.select_one("img")
        rows.append({
            "scraped_at": now_utc_iso(), "source_shop": SHOP_NAME,
            "product_id": product_id, "variant_id": variant_id,
            "product_key": f"vinyleers:{product_url}:{variant_id}",
            "artist": artist, "title": title, "format": _first_text(card, ".format-block") or "Vinyl",
            "price": price, "standard_price": standard_price, "currency": MARKET_CURRENCY,
            "is_sale": "true" if standard_price else "false",
            "availability": extract_availability(card), "product_url": product_url,
            "image_url": normalize_image_url(image.get("data-src") or image.get("src") if image else ""),
            "page_found": str(page), "new_badge": "true", "is_secondhand": "false",
        })
    next_node = soup.select_one(".pagination a.next[href]")
    return rows, normalize_url(next_node.get("href")) if next_node else None, identities, skips


class VinyleersClient:
    def __init__(self, session: requests.Session, delay_seconds: float = DEFAULT_DELAY_SECONDS):
        if delay_seconds < 0.5:
            raise ValueError("delay_seconds must be >= 0.5")
        self.session = session
        self.delay_seconds = delay_seconds
        self.last_request_at: float | None = None

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
                raise RuntimeError(f"Vinyleers rate limit reached (HTTP 429): {url}")
            if response.status_code in {500, 502, 503, 504} and attempt < 2:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.text
        raise RuntimeError(f"Vinyleers transient HTTP failure: {url}")


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "VinylofyVinyleers/1.0 (+https://vinylofy.com)",
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    })
    return session


def scrape_listings(client: VinyleersClient, max_pages: int = 0) -> tuple[list[dict[str, str]], Counter[str], int]:
    if max_pages < 0:
        raise ValueError("max_pages must be >= 0")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    seen_page_sets: set[frozenset[str]] = set()
    skips: Counter[str] = Counter()
    page = 1
    pages_processed = 0
    last_page: int | None = None
    while max_pages == 0 or page <= max_pages:
        html = client.get(listing_page_url(page))
        page_rows, _next, identities, page_skips = parse_listing_page(html, page)
        skips.update(page_skips)
        if not identities:
            skips["empty_product_page"] += 1
            break
        page_set = frozenset(identities)
        if page_set in seen_page_sets:
            skips["repeated_product_variant_set"] += 1
            break
        seen_page_sets.add(page_set)
        pages_processed = page
        last_page = extract_last_page(html) or last_page
        for row in page_rows:
            if row["product_key"] in seen:
                skips["duplicate_product_variant_between_pages"] += 1
            else:
                seen.add(row["product_key"])
                rows.append(row)
        print(f"[PAGE {page}] cards={len(identities)} accepted={len(page_rows)} total={len(rows)}", flush=True)
        if last_page is not None and page >= last_page:
            print(f"[STOP] reached terminal listing page {last_page}", flush=True)
            break
        page += 1
    return rows, skips, pages_processed


def _valid_ean(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits if len(digits) in {8, 12, 13, 14} else ""


def parse_detail_page(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main") or soup
    text = clean(main.get_text(" ", strip=True))
    eans = [_valid_ean(value) for value in PRODUCT_BARCODE_RE.findall(html)]
    eans += [_valid_ean(match.group(1)) for match in EAN_LABEL_RE.finditer(text)]
    eans = list(dict.fromkeys(value for value in eans if value))
    detail_price = ""
    price_match = PRODUCT_PRICE_RE.search(html)
    if price_match:
        detail_price = parse_money(price_match.group(1))
    if not detail_price:
        price_node = main.select_one(".price .theme-money, .product-price .theme-money")
        detail_price = parse_money(price_node.get_text(" ", strip=True) if price_node else "")
    comment_match = re.search(r"Comments?\s*:\s*(.*?)(?:Wat is ultrasone|Inpakservice|$)", text, re.I)
    comment = clean(comment_match.group(1) if comment_match else "")
    new_evidence = bool(re.search(r"\bnew\s*(?:&|and)\s*sealed\b", comment, re.I))
    secondhand = bool(re.search(r"\b(?:tweedehands|second[- ]hand|used record|used vinyl)\b", comment, re.I))
    available_match = PRODUCT_AVAILABLE_RE.search(html)
    availability = "in_stock" if available_match and available_match.group(1).casefold() == "true" else "unknown"
    return {
        "ean": eans[0] if len(eans) == 1 else "",
        "detail_price": detail_price,
        "new_evidence": "true" if new_evidence else "false",
        "is_secondhand": "true" if secondhand or not new_evidence else "false",
        "availability": availability,
        "detail_status": "ok" if len(eans) == 1 else "missing_ean",
        "detail_error": "",
    }


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
            break
    if selected:
        state["cursor"] = (last_index + 1) % len(rows)
    return selected


def apply_cached_details(rows: list[dict[str, str]], state: dict) -> None:
    for row in rows:
        cached = state["details"].get(row["product_url"], {})
        for key in ("ean", "detail_price", "new_evidence", "is_secondhand", "detail_status", "detail_error", "enriched_at"):
            if key in cached:
                row[key] = cached[key]


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MASTER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def scrape(*, max_pages: int, detail_limit: int, delay_seconds: float, detail_state_file: Path) -> tuple[list[dict[str, str]], dict]:
    if not 0 <= detail_limit <= MAX_DETAIL_BATCH:
        raise ValueError(f"detail_limit must be between 0 and {MAX_DETAIL_BATCH}")
    client = VinyleersClient(build_session(), delay_seconds)
    rows, skips, pages = scrape_listings(client, max_pages)
    state = load_detail_state(detail_state_file)
    apply_cached_details(rows, state)
    detail_rows = select_detail_rows(rows, state, detail_limit)
    for row in detail_rows:
        try:
            details = parse_detail_page(client.get(row["product_url"]))
            row.update(details)
        except (requests.RequestException, RuntimeError) as exc:
            row.update({"ean": "", "detail_price": "", "new_evidence": "false", "is_secondhand": "true", "detail_status": "technical_error", "detail_error": type(exc).__name__})
        row["price_match"] = "true" if row.get("detail_price") and row.get("detail_price") == row.get("price") else "false"
        row["enriched_at"] = now_utc_iso()
        state["details"][row["product_url"]] = {key: row.get(key, "") for key in ("ean", "detail_price", "new_evidence", "is_secondhand", "detail_status", "detail_error", "enriched_at")}
        save_detail_state(detail_state_file, state)
    apply_cached_details(rows, state)
    for row in rows:
        row["price_match"] = "true" if row.get("detail_price") and row.get("detail_price") == row.get("price") else "false"
    samples = []
    for row in rows[:SAMPLE_CHECK_LIMIT]:
        samples.append({
            "product_url": row["product_url"], "artist": row["artist"], "title": row["title"],
            "listing_price": row["price"], "detail_price": row.get("detail_price", ""),
            "price_match": row.get("price_match", "false"), "new_badge": row.get("new_badge", "false"),
            "new_evidence": row.get("new_evidence", ""), "ean": row.get("ean", ""),
        })
    summary = {
        "pages": pages, "products": len(rows), "detail_attempted": len(detail_rows),
        "detail_resolved": sum(row.get("detail_status") in RESOLVED_DETAIL_STATUSES for row in rows),
        "detail_pending": sum(row.get("detail_status") not in RESOLVED_DETAIL_STATUSES for row in rows),
        "skips": dict(skips), "sample_checks": samples,
    }
    return rows, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vinyleers new-vinyl listing/detail scraper")
    parser.add_argument("--max-pages", type=int, default=1, help="0 follows pagination until the terminal page")
    parser.add_argument("--detail-limit", type=int, default=5, help="detail pages per run, maximum 500")
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/vinyleers"))
    parser.add_argument("--detail-state-file", type=Path, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_pages < 0 or not 0 <= args.detail_limit <= MAX_DETAIL_BATCH or args.delay_seconds < 0.5:
        raise SystemExit("max-pages >= 0, detail-limit 0..500 en delay-seconds >= 0.5 vereist")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_file = args.detail_state_file or args.output_dir / "vinyleers_detail_state.json"
    rows, summary = scrape(max_pages=args.max_pages, detail_limit=args.detail_limit, delay_seconds=args.delay_seconds, detail_state_file=state_file)
    write_rows(args.output_dir / "vinyleers_products.csv", rows)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output_dir / "sample_checks.json").write_text(json.dumps(summary["sample_checks"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
