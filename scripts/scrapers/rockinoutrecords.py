#!/usr/bin/env python3
"""Bounded listing/detail pilot for Rockin' Out Records (Windows-safe)."""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://rockinoutrecords.nl"
CATEGORY_URL = f"{BASE_URL}/product-category/vinyl-lp-nieuw/"
DOMAIN = "rockinoutrecords.nl"
SHOP_NAME = "Rockin' Out Records"
LISTING_FIELDS = ("source_shop", "product_id", "product_key", "artist", "title", "format", "price",
                  "standard_price", "is_sale", "availability", "product_url", "image_url", "page_found", "scraped_at")
MASTER_FIELDS = LISTING_FIELDS + ("ean", "detail_status", "detail_error", "enriched_at")
RESOLVED_DETAIL_STATUSES = {"ok", "missing_ean"}


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def normalize_url(value: str | None) -> str:
    absolute = urljoin(BASE_URL, value or "")
    parsed = urlsplit(absolute)
    if parsed.scheme != "https" or parsed.hostname not in {DOMAIN, f"www.{DOMAIN}"}:
        return ""
    return f"https://{DOMAIN}{parsed.path.rstrip('/')}/" if parsed.path != "/" else f"https://{DOMAIN}/"


def parse_money(value: str) -> str:
    match = re.search(r"\d{1,3}(?:\.\d{3})*,\d{1,2}|\d+(?:[.,]\d{1,2})?", clean(value))
    if not match:
        return ""
    raw = match.group(0)
    raw = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    try:
        amount = float(raw)
    except ValueError:
        return ""
    return f"{amount:.2f}" if amount > 0 else ""


def extract_availability(card: BeautifulSoup) -> str:
    """Use explicit buy/info CTAs as stock evidence; do not infer stock by absence."""
    buy_markers = ("in winkelwagen", "toevoegen aan winkelwagen", "add to cart", "buy now")
    info_markers = ("meer informatie", "more information", "more info")
    for control in card.select("a, button"):
        text = clean(control.get_text(" ", strip=True)).casefold()
        classes = " ".join(control.get("class", [])).casefold()
        if any(marker in text for marker in buy_markers) or "add_to_cart" in classes:
            if control.get("aria-disabled") != "true" and "disabled" not in classes:
                return "in_stock"
        if any(marker in text for marker in info_markers):
            return "out_of_stock"
    if "outofstock" in card.get("class", []):
        return "out_of_stock"
    return "unknown"


def parse_listing_page(html: str, page: int) -> tuple[list[dict[str, str]], str | None, dict[str, int]]:
    soup = BeautifulSoup(html, "html.parser")
    rows, skips, seen = [], {}, set()
    next_node = soup.find("link", rel="next")
    next_url = normalize_url(next_node.get("href")) if next_node else None
    for card in soup.select("li.product"):
        link = card.select_one("a.woocommerce-loop-product__link, a.ast-loop-product__link")
        title_node = card.select_one(".woocommerce-loop-product__title")
        url = normalize_url(link.get("href") if link else "")
        title = clean(title_node.get_text(" ", strip=True) if title_node else "")
        price = parse_money(card.select_one(".price").get_text(" ", strip=True) if card.select_one(".price") else "")
        if not url: skips["missing_product_url"] = skips.get("missing_product_url", 0) + 1; continue
        if url in seen: skips["duplicate_product_url"] = skips.get("duplicate_product_url", 0) + 1; continue
        if not title or not price: skips["missing_title_or_price"] = skips.get("missing_title_or_price", 0) + 1; continue
        seen.add(url)
        parts = re.split(r"\s*[|–—-]\s*", title, maxsplit=1)
        artist, album = (parts[0], parts[1]) if len(parts) == 2 else ("", title)
        product_id = clean(card.get("class", []))
        rows.append({"source_shop": SHOP_NAME, "product_id": product_id, "product_key": f"rockinoutrecords:{url}",
                     "artist": artist, "title": album, "format": "Vinyl LP", "price": price,
                     "standard_price": price, "is_sale": "false",
                     "availability": extract_availability(card),
                     "product_url": url, "image_url": normalize_url((card.select_one("img") or {}).get("src", "")) if card.select_one("img") else "",
                     "page_found": str(page), "scraped_at": datetime.now(timezone.utc).isoformat()})
    return rows, next_url, skips


def parse_detail_page(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    codes: set[str] = set()
    for node in soup.select('script[type="application/ld+json"]'):
        try: value = json.loads(node.string or node.get_text())
        except (TypeError, json.JSONDecodeError): continue
        nodes = value.get("@graph", []) if isinstance(value, dict) and isinstance(value.get("@graph"), list) else [value]
        for item in nodes:
            if not isinstance(item, dict) or item.get("@type") != "Product": continue
            for key in ("gtin", "gtin12", "gtin13", "gtin14", "ean"):
                raw = item.get(key)
                digits = re.sub(r"\D", "", str(raw or ""))
                if len(digits) in {8, 12, 13, 14}: codes.add(digits)
    return next(iter(codes)) if len(codes) == 1 else ""


def load_detail_state(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "cursor": 0, "details": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "cursor": 0, "details": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("details", {}), dict):
        return {"version": 1, "cursor": 0, "details": {}}
    return {"version": 1, "cursor": int(raw.get("cursor", 0) or 0), "details": raw["details"]}


def save_detail_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def select_detail_rows(rows: list[dict[str, str]], state: dict, limit: int) -> list[dict[str, str]]:
    if not rows or limit <= 0:
        return []
    cursor = int(state.get("cursor", 0) or 0) % len(rows)
    selected: list[dict[str, str]] = []
    selected_urls: set[str] = set()
    last_index = cursor
    for offset in range(len(rows)):
        index = (cursor + offset) % len(rows)
        row = rows[index]
        url = row["product_url"]
        cached = state.get("details", {}).get(url, {})
        if cached.get("detail_status") in RESOLVED_DETAIL_STATUSES:
            continue
        selected.append(row)
        selected_urls.add(url)
        last_index = index
        if len(selected) >= limit:
            state["cursor"] = (last_index + 1) % len(rows)
            return selected
    if selected_urls:
        state["cursor"] = (last_index + 1) % len(rows)
    return selected


def apply_cached_details(rows: list[dict[str, str]], state: dict) -> None:
    for row in rows:
        cached = state.get("details", {}).get(row["product_url"], {})
        row.update(
            {
                "ean": cached.get("ean", ""),
                "detail_status": cached.get("detail_status", "not_sampled"),
                "detail_error": cached.get("detail_error", ""),
                "enriched_at": cached.get("enriched_at", ""),
            }
        )


def scrape(*, max_pages: int, detail_limit: int, delay_seconds: float, detail_state_file: Path | None = None) -> tuple[list[dict[str, str]], dict]:
    session = requests.Session(); session.headers.update({"User-Agent": "Vinylofy-RockinOut-Pilot/1.0"})
    rows, skips, visited = [], {}, set(); url = CATEGORY_URL; page = 0
    state = load_detail_state(detail_state_file) if detail_state_file else {"version": 1, "cursor": 0, "details": {}}
    while url and url not in visited and (max_pages == 0 or page < max_pages):
        page += 1
        if not url or url in visited: break
        visited.add(url)
        response = session.get(url, timeout=30); response.raise_for_status()
        found, next_url, page_skips = parse_listing_page(response.text, page)
        for key, count in page_skips.items(): skips[key] = skips.get(key, 0) + count
        rows.extend(row for row in found if row["product_url"] not in {item["product_url"] for item in rows})
        if not next_url: break
        url = next_url; time.sleep(delay_seconds)
    apply_cached_details(rows, state)
    detail_rows = select_detail_rows(rows, state, detail_limit)
    for row in detail_rows:
        try:
            response = session.get(row["product_url"], timeout=30); response.raise_for_status()
            row["ean"] = parse_detail_page(response.text); row["detail_status"] = "ok" if row["ean"] else "missing_ean"
            row["detail_error"] = ""
        except requests.RequestException as exc:
            row["ean"] = ""; row["detail_status"] = "error"; row["detail_error"] = type(exc).__name__
        row["enriched_at"] = datetime.now(timezone.utc).isoformat(); time.sleep(delay_seconds)
        state["details"][row["product_url"]] = {
            "ean": row["ean"], "detail_status": row["detail_status"],
            "detail_error": row["detail_error"], "enriched_at": row["enriched_at"],
        }
        if detail_state_file:
            save_detail_state(detail_state_file, state)
    apply_cached_details(rows, state)
    resolved = sum(row["detail_status"] in RESOLVED_DETAIL_STATUSES for row in rows)
    return rows, {
        "pages": len(visited), "products": len(rows),
        "detail_attempted": len(detail_rows), "detail_cached_resolved": resolved,
        "detail_pending": len(rows) - resolved, "skips": skips,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=0, help="0 = follow pagination until the shop stops")
    parser.add_argument("--detail-limit", type=int, default=5)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/rockinoutrecords"))
    parser.add_argument("--detail-state-file", type=Path, default=None)
    args = parser.parse_args()
    if args.max_pages < 0 or not 0 <= args.detail_limit <= 250 or args.delay_seconds < 0.5:
        parser.error("max-pages >= 0, detail-limit 0..250 and delay-seconds >= 0.5 required")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_file = args.detail_state_file or (args.output_dir / "rockinoutrecords_detail_state.json")
    rows, summary = scrape(max_pages=args.max_pages, detail_limit=args.detail_limit, delay_seconds=args.delay_seconds, detail_state_file=state_file)
    output = args.output_dir / "rockinoutrecords_products.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MASTER_FIELDS); writer.writeheader(); writer.writerows(rows)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
