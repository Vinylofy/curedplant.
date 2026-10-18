"""Opt-in evidence from native listing parsers; never fetches or writes a DB."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit


def capture(record):
    path = os.environ.get("CUREDPLANT_PRICE_EVIDENCE")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def capture_link(link):
    # Only these native collectors do not construct ListingOffer objects.
    if link.shop_id not in {"dgmoutlet", "fiftiesstore", "imusic", "jpc", "musiconvinyl"}:
        return
    p = link.payload
    keys = {"dgmoutlet": "price_current", "fiftiesstore": "price",
            "imusic": "listing_price_raw", "jpc": "listing_price_raw",
            "musiconvinyl": "chosen_price"}
    capture({"source_url": link.source_url, "price": p.get(keys[link.shop_id]),
             "currency": p.get("listing_currency") or p.get("currency") or "EUR",
             "ean": p.get("ean"), "availability": p.get("availability") or p.get("listing_availability"),
             "raw": p, "kind": "native_listing"})


def url_key(value):
    parsed = urlsplit(str(value or ""))
    host = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"^/collections/[^/]+/products/", "/products/", parsed.path).rstrip("/")
    if host == "variaworld.nl" and path == "/artikel/detail.php":
        article = parse_qs(parsed.query).get("at")
        if article and len(article) == 1 and article[0].isdigit():
            path += "?at=" + article[0]
    if host == "imusic.nl":
        match = re.match(r"/music/(\d{12,14})(?:/|$)", path)
        if match:
            path = "/music/" + match[1]
    if host == "jpc.de":
        match = re.search(r"/hnum/(\d+)(?:/|$)", path)
        if match:
            path = "/hnum/" + match[1]
    return host + path


def amount(value):
    """Reject shipping text and ambiguous amounts instead of regex guessing."""
    text = str(value or "").strip().replace("\u00a0", "").replace("€", "").replace("EUR", "").strip()
    if not re.fullmatch(r"\d+(?:[.,]\d{1,2})?", text):
        return None
    try:
        result = Decimal(text.replace(",", ".")).quantize(Decimal("0.01"))
        return result if result.is_finite() and result > 0 else None
    except InvalidOperation:
        return None


def assess(records):
    by_url, errors = {}, []
    for record in records:
        if record.get("kind") == "source_error":
            errors.append(record)
            continue
        url = record.get("source_url")
        if not url or urlsplit(url).scheme not in {"https", "http"}:
            errors.append({"url": url, "reason": "invalid_product_url"})
            continue
        value = amount(record.get("price"))
        if value is None:
            # Missing listing amounts are counted, never converted to prices.
            continue
        normalized = dict(record, price=str(value), currency=record.get("currency") or "EUR")
        previous = by_url.get(url_key(url))
        if previous and previous["price"] != normalized["price"]:
            errors.append({"url": url, "reason": "conflicting_listing_prices",
                           "prices": [previous["price"], normalized["price"]]})
        by_url[url_key(url)] = normalized
    rows = list(by_url.values())
    counts = Counter(row["price"] for row in rows)
    dominant = counts.most_common(1)[0] if counts else (None, 0)
    if not rows:
        errors.append({"reason": "no_valid_current_listing_prices"})
    if records and sum(amount(r.get("price")) is not None for r in records) / len(records) < .8:
        errors.append({"reason": "less_than_80_percent_valid_listing_prices"})
    if len(rows) >= 50 and dominant[1] / len(rows) >= .95:
        errors.append({"reason": "dominant_identical_price_requires_review", "price": dominant[0], "count": dominant[1]})
    return rows, {"status": "red" if errors else "green", "observations": len(records),
                  "priced_products": len(rows), "missing_or_invalid_price": len(records) - sum(amount(r.get("price")) is not None for r in records),
                  "distinct_prices": len(counts), "dominant_price": dominant[0],
                  "dominant_count": dominant[1], "error_count": len(errors),
                  "errors": errors[:25], "samples": rows[:12]}
