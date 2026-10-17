#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from psycopg.rows import dict_row

from scripts.scrapers.usf.core.db import db_connection
from scripts.scrapers.usf.core.soundsvenlo_transport import SoundsVenloSession
from scripts.importers.common import strict_normalize_gtin
from scripts.scrapers.usf.core.link_registry import (
    insert_raw_shop_scrape,
    mark_detail_scraped,
)


SHOP_ID = "soundsvenlo"
BASE_URL = "https://www.sounds-venlo.nl"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; Vinylofy-USF/1.0; +https://vinylofy.nl)"
)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def normalize_price(value: object) -> str | None:
    text = clean(value)
    if not text:
        return None
    text = text.replace("€", "").replace("EUR", "").strip()
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    match = re.search(r"([0-9]+(?:\.[0-9]{1,2})?)", text)
    if not match:
        return None
    amount = match.group(1)
    if "." not in amount:
        return f"{amount}.00"
    whole, cents = amount.split(".", 1)
    return f"{whole}.{cents[:2].ljust(2, '0')}"


def normalize_availability(value: object) -> str:
    text = clean(value).lower()
    if not text:
        return "unknown"
    text = text.replace("-", "_").replace(" ", "_")
    aliases = {
        "ja": "in_stock",
        "nee": "out_of_stock",
        "op_voorraad": "in_stock",
        "in_stock": "in_stock",
        "instock": "in_stock",
        "niet_leverbaar": "out_of_stock",
        "tijdelijk_niet_leverbaar": "out_of_stock",
        "(tijdelijk)_niet_leverbaar": "out_of_stock",
        "uitverkocht": "out_of_stock",
        "out_of_stock": "out_of_stock",
        "outofstock": "out_of_stock",
        "pre_order": "preorder",
        "preorder": "preorder",
        "verwacht": "preorder",
    }
    return aliases.get(text, "unknown")


def normalize_ean(value: object) -> str | None:
    return strict_normalize_gtin(value)


def normalize_product_url(value: object) -> str:
    text = clean(value).split("#", 1)[0].split("?", 1)[0].rstrip("/")
    return text + "/" if text else text


def fetch_detail_queue(
    *,
    limit: int,
    retry_days: int,
) -> list[dict[str, Any]]:
    """Queue only missing EAN/enrichment records, not the full catalog.

    The large-catalog policy is enforced by:
    - using shop_product_links as source of truth for active URLs;
    - prioritising URLs without a raw detail snapshot;
    - retrying successful no-EAN detail attempts at most three times;
    - throttling rechecks through last_detail_scraped_at/retry_days.
    """
    with db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                with link_rows as (
                    select
                        l.id,
                        l.shop_id,
                        l.source_url,
                        trim(trailing '/' from split_part(l.source_url, '?', 1)) as source_url_norm,
                        l.source_product_id,
                        l.payload,
                        l.first_seen_at,
                        l.last_seen_at,
                        l.last_detail_scraped_at
                    from public.shop_product_links l
                    where l.shop_id = %s
                      and l.status = 'active'
                      and l.source_url is not null
                ),
                latest_raw as (
                    select distinct on (
                        r.shop_id,
                        trim(trailing '/' from split_part(r.source_url, '?', 1))
                    )
                        r.shop_id,
                        trim(trailing '/' from split_part(r.source_url, '?', 1)) as source_url_norm,
                        r.id as raw_scrape_id,
                        r.ean_raw,
                        r.image_url_raw,
                        r.payload as raw_payload,
                        r.scraped_at
                    from public.raw_shop_scrapes r
                    where r.shop_id = %s
                    order by
                        r.shop_id,
                        trim(trailing '/' from split_part(r.source_url, '?', 1)),
                        r.scraped_at desc nulls last,
                        r.id desc
                ),
                raw_attempts as (
                    select
                        r.shop_id,
                        trim(trailing '/' from split_part(r.source_url, '?', 1)) as source_url_norm,
                        count(*) as attempts,
                        count(*) filter (where r.ean_raw is null) as missing_ean_attempts
                    from public.raw_shop_scrapes r
                    where r.shop_id = %s
                    group by
                        r.shop_id,
                        trim(trailing '/' from split_part(r.source_url, '?', 1))
                )
                select
                    l.id,
                    l.shop_id,
                    l.source_url,
                    l.source_product_id,
                    l.payload,
                    l.last_detail_scraped_at,
                    lr.raw_scrape_id,
                    lr.ean_raw as latest_ean_raw,
                    lr.image_url_raw as latest_image_url_raw,
                    lr.raw_payload,
                    coalesce(ra.attempts, 0) as detail_attempts,
                    coalesce(ra.missing_ean_attempts, 0) as missing_ean_attempts
                from link_rows l
                left join latest_raw lr
                  on lr.shop_id = l.shop_id
                 and lr.source_url_norm = l.source_url_norm
                left join raw_attempts ra
                  on ra.shop_id = l.shop_id
                 and ra.source_url_norm = l.source_url_norm
                where
                    (
                        lr.raw_scrape_id is null
                        or (
                            lr.ean_raw is null
                            and coalesce(ra.missing_ean_attempts, 0) < 3
                        )
                        or (
                            lr.ean_raw is not null
                            and (
                                coalesce(lr.image_url_raw, '') = ''
                                or coalesce(lr.raw_payload->>'genre', '') = ''
                                or coalesce(lr.raw_payload->>'label', '') = ''
                            )
                        )
                    )
                    and (
                        l.last_detail_scraped_at is null
                        or l.last_detail_scraped_at < now() - (%s * interval '1 day')
                        or lr.raw_scrape_id is null
                    )
                order by
                    case when lr.raw_scrape_id is null then 0 else 1 end,
                    l.first_seen_at asc nulls last,
                    l.id asc
                limit %s
                """,
                (SHOP_ID, SHOP_ID, SHOP_ID, retry_days, limit),
            )
            return [dict(row) for row in cur.fetchall()]


def get_listing_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}


def get_listing_price(row: dict[str, Any]) -> str | None:
    payload = get_listing_payload(row)
    return normalize_price(payload.get("price"))


def get_listing_availability(row: dict[str, Any]) -> str:
    payload = get_listing_payload(row)
    return normalize_availability(payload.get("availability"))


def extract_ean_from_url(source_url: str) -> str | None:
    slug = urlparse(source_url).path.strip("/").split("/")[-1]
    for match in re.finditer(r"(?<!\d)(\d{12,14})(?!\d)", slug):
        ean = normalize_ean(match.group(1))
        if ean:
            return ean
    return None


def product_scope(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('main h1')
    if heading is None:
        return None
    group = heading.find_parent('hgroup') or heading
    parent = group.find_parent('div')
    if parent is None:
        return None
    scope = BeautifulSoup(str(parent), 'html.parser')
    for node in scope.select('script, style, form, template, svg, nav, .group'):
        node.decompose()
    return scope


def ean_evidence(html: str, source_url: str) -> dict[str, Any]:
    candidates: dict[str, list[str]] = {}
    offer_availability = None
    def add(value, origin):
        ean = normalize_ean(value)
        if ean:
            candidates.setdefault(ean, []).append(origin)

    scope = product_scope(html)
    if scope is not None:
        for line in scope.stripped_strings:
            if re.fullmatch(r'\d{12,14}', clean(line)):
                add(clean(line), 'product_metadata_line')
        text = clean(scope.get_text(' ', strip=True))
        for match in re.finditer(r'\b(?:EAN|GTIN|Barcode|Streepjescode)\s*:?\s*(\d{8,14})(?!\d)', text, re.I):
            add(match.group(1), 'product_labelled_barcode')

    # Only the structured Product belonging to this URL can add identifiers.
    soup = BeautifulSoup(html, 'html.parser')
    wanted = normalize_product_url(source_url)
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.get_text())
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if not isinstance(item, dict):
                continue
            stack.extend(item.get('@graph', []))
            types = item.get('@type', [])
            types = [types] if isinstance(types, str) else types
            if 'Product' not in types or normalize_product_url(item.get('url', '')) != wanted:
                continue
            offer = item.get('offers')
            if isinstance(offer, dict):
                offer_availability = offer.get('availability')
            for key in ('gtin', 'gtin8', 'gtin12', 'gtin13', 'gtin14', 'barcode'):
                if item.get(key):
                    add(item[key], 'current_product_jsonld')
    from_url = extract_ean_from_url(source_url)
    if from_url:
        add(from_url, 'product_url')
    ean = next(iter(candidates)) if len(candidates) == 1 else None
    return {'ean': ean, 'candidates': sorted(candidates),
            'detail_availability_observed': offer_availability,
            'source': candidates.get(ean, []),
            'issue': 'ambiguous_product_eans' if len(candidates) > 1 else 'missing_valid_product_ean' if not ean else None}


def extract_ean(html: str, source_url: str) -> str | None:
    return ean_evidence(html, source_url)['ean']


def extract_image_url(html: str) -> str | None:
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'"image"\s*:\s*"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            image_url = match.group(1).replace("\\/", "/")
            if image_url.startswith("//"):
                image_url = "https:" + image_url
            elif image_url.startswith("/"):
                image_url = BASE_URL + image_url
            return image_url
    return None


def extract_detail_text_lines(html: str) -> list[str]:
    soup = product_scope(html)
    if soup is None:
        return []
    return [
        clean(line)
        for line in soup.get_text("\n", strip=True).splitlines()
        if clean(line)
    ]


def extract_detail_metadata(html: str) -> dict[str, str | None]:
    lines = extract_detail_text_lines(html)
    metadata: dict[str, str | None] = {
        "genre": None,
        "label": None,
        "format": None,
        "release_date": None,
        "detail_product_id": None,
    }

    scope = product_scope(html)
    if scope is not None:
        for link in scope.select('a[href]'):
            href, title = str(link.get('href', '')), clean(link.get_text(' ', strip=True))
            if '/artiest-' in href:
                continue
            if re.fullmatch(r'(?:\d*\s*(?:LP|CD)|(?:7|10|12)\s*(?:inch|"))', title, re.I):
                metadata['format'] = title
            elif metadata['genre'] is None:
                metadata['genre'] = title or None

    for index, line in enumerate(lines):
        release = re.search(r'\bRelease\s*:?\s*(\d{2}-\d{2}-\d{4})', line, re.I)
        if release:
            metadata['release_date'] = release.group(1)
        label = re.fullmatch(r'(?:Label|Maatschappij)\s*:\s*(.+)', line, re.I)
        if label:
            metadata['label'] = label.group(1)
        if re.fullmatch(r'\d{6,9}', line):
            metadata['detail_product_id'] = line
        if line.lower() == "release" and index + 1 < len(lines):
            metadata["release_date"] = clean(lines[index + 1])
            continue
        if re.fullmatch(r"\d{2}-\d{2}-\d{4}", line):
            metadata["release_date"] = line
            continue

    return metadata


def build_title_raw(listing_payload: dict[str, Any], html: str) -> str | None:
    artist = clean(listing_payload.get("artist"))
    title = clean(listing_payload.get("title"))
    if artist and title:
        return f"{artist} | {title}"

    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    detail_title = clean(h1.get_text(" ", strip=True)) if h1 else ""
    if detail_title:
        return detail_title
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch Sounds Venlo detail pages into raw_shop_scrapes."
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--sleep", type=float, default=0.50)
    parser.add_argument("--retry-days", type=int, default=30)
    parser.add_argument("--write", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.limit < 1:
        raise SystemExit("[ERROR] --limit moet minimaal 1 zijn.")
    if args.sleep < 0:
        raise SystemExit("[ERROR] --sleep mag niet negatief zijn.")
    if args.retry_days < 1:
        raise SystemExit("[ERROR] --retry-days moet minimaal 1 zijn.")

    with SoundsVenloSession() as session:
        return run_detail(args, session)


def run_detail(args, session) -> int:

    links = fetch_detail_queue(limit=args.limit, retry_days=args.retry_days)
    print(
        "[DETAIL]",
        {
            "shop": SHOP_ID,
            "queued": len(links),
            "write": args.write,
            "retry_days": args.retry_days,
        },
        flush=True,
    )

    if not links:
        return 0

    stored = 0
    skipped = 0
    fetched = 0
    ean_hits = 0
    errors = 0

    for index, link in enumerate(links, start=1):
        source_url = normalize_product_url(link["source_url"])
        listing_payload = get_listing_payload(link)

        print(
            "[DETAIL]",
            {
                "index": index,
                "total": len(links),
                "url": source_url,
                "attempts": link.get("detail_attempts"),
            },
            flush=True,
        )

        try:
            response = session.get(source_url, timeout=30)
        except requests.RequestException as exc:
            skipped += 1
            errors += 1
            print("[DETAIL][WARN] request failed", {"url": source_url, "error": str(exc)}, flush=True)
            continue

        if response.status_code in {403, 429}:
            errors += 1
            print("[DETAIL][WARN] blocked, stopping safely.", flush=True)
            break

        if response.status_code in (404, 410):
            print(
                "[DETAIL][SKIP] dead link",
                {"status": response.status_code, "url": source_url},
                flush=True,
            )
            if args.write:
                mark_detail_scraped(link["id"])
            skipped += 1
            continue

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            skipped += 1
            errors += 1
            print("[DETAIL][WARN] HTTP error", {"url": source_url, "error": str(exc)}, flush=True)
            continue

        html = response.text
        evidence = ean_evidence(html, source_url)
        ean_raw = evidence['ean']
        fetched += 1
        ean_hits += bool(ean_raw)
        metadata = extract_detail_metadata(html)
        image_url_raw = extract_image_url(html)
        title_raw = build_title_raw(listing_payload, html)
        price_raw = get_listing_price(link)
        availability_raw = get_listing_availability(link)
        source_product_id = (
            clean(metadata.get("detail_product_id"))
            or clean(link.get("source_product_id"))
            or urlparse(source_url).path.strip("/").split("/")[-1]
        )

        if not args.write:
            print("[DETAIL-PARSED]", {"url": source_url, "ean": ean_raw}, flush=True)
            time.sleep(args.sleep)
            continue

        raw_id = insert_raw_shop_scrape(
            run_id=None,
            shop_id=SHOP_ID,
            source_url=source_url,
            source_product_id=source_product_id,
            title_raw=title_raw,
            ean_raw=ean_raw,
            price_raw=price_raw,
            availability_raw=availability_raw,
            image_url_raw=image_url_raw,
            payload={
                "source": "detail_soundsvenlo",
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "html_length": len(html),
                "status_code": response.status_code,
                "detail_price_policy": "current_price_from_listing_payload_only",
                "listing_payload": listing_payload,
                "genre": metadata.get("genre"),
                "label": metadata.get("label"),
                "format": metadata.get("format") or listing_payload.get("format"),
                "release_date": metadata.get("release_date"),
                "detail_product_id": metadata.get("detail_product_id"),
                "ean_evidence": evidence,
            },
        )
        mark_detail_scraped(link["id"])
        stored += 1

        print(
            "[DETAIL] stored",
            {
                "raw_id": raw_id,
                "ean": ean_raw,
                "price_from_listing": price_raw,
                "availability_from_listing": availability_raw,
            },
            flush=True,
        )

        time.sleep(args.sleep)

    print(
        "[DETAIL] done",
        {"stored": stored, "skipped": skipped, "fetched": fetched, "ean_hits": ean_hits, "errors": errors, "write": args.write},
        flush=True,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
