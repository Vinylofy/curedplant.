"""One-time, resumable repair of technical product titles from exact Bol EAN data."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import uuid

import psycopg
from psycopg.rows import dict_row

from scripts.importers.bol_api_review import authenticate, request_json, ReviewError, CATALOG_URL
from scripts.importers.common import strict_normalize_gtin

STATE_PATH = Path("state/bol-metadata/nl.json")
OUTPUT_PATH = Path("output/bol-metadata/result.json")
TECHNICAL_RE = re.compile(
    r"^(?:(?:vinyl|lp|record)(?:\s+(?:ean|upc))?\s*)?\d{8,14}$|^unknown(?:\s+(?:album|title))?$",
    re.I,
)
UNKNOWN_ARTIST_RE = re.compile(r"^(?:unknown artist|onbekende artiest)$", re.I)
VINYL_RE = re.compile(r"(?:^|\b)(?:vinyl|lp|7\s*(?:inch|\")|10\s*(?:inch|\")|12\s*(?:inch|\"))(?:\b|$)", re.I)
BLOCKED_MEDIA_RE = re.compile(r"\b(?:cd|dvd|blu-?ray|cassette|download|digital)\b", re.I)
ARTIST_LABELS = {"artiest", "artiesten", "artiest(en)", "uitvoerend artiest", "artist", "artists"}
MEDIA_LABELS = {"drager", "muziekdrager", "media", "format", "formaat"}


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def technical_title(value) -> bool:
    value = clean(value)
    return not value or bool(TECHNICAL_RE.fullmatch(value))


def valid_artist(value) -> bool:
    value = clean(value)
    return bool(value and not UNKNOWN_ARTIST_RE.fullmatch(value) and not value.isdigit())


def response_values(response: dict, wanted: set[str]) -> list[str]:
    found: list[str] = []
    groups = response.get("specificationGroups")
    if not isinstance(groups, list):
        return found
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("specifications"), list):
            continue
        for item in group["specifications"]:
            if not isinstance(item, dict) or clean(item.get("name")).casefold() not in wanted:
                continue
            values = item.get("values")
            if not isinstance(values, list):
                values = [values]
            found.extend(clean(value) for value in values if clean(value))
    return found


def normalize_response(product: dict, response: dict) -> dict:
    existing_gtin = strict_normalize_gtin(product.get("ean"))
    response_gtin = strict_normalize_gtin(response.get("ean")) if isinstance(response, dict) else None
    if not existing_gtin or response_gtin != existing_gtin:
        raise ValueError("response_ean_mismatch")
    title = clean(response.get("title"))
    if technical_title(title):
        raise ValueError("missing_or_technical_bol_title")
    media = response_values(response, MEDIA_LABELS)
    if not media or any(BLOCKED_MEDIA_RE.search(value) for value in media) or not any(VINYL_RE.search(value) for value in media):
        raise ValueError("bol_format_not_proven_vinyl")
    artists = response_values(response, ARTIST_LABELS)
    artist = next((value for value in artists if valid_artist(value)), None)
    if not artist:
        artist = clean(product.get("artist"))
    if not valid_artist(artist):
        raise ValueError("artist_unavailable")
    return {"artist": artist, "title": title, "media": media, "bol_product_id": clean(response.get("bolProductId")) or None}


class Client:
    def __init__(self):
        self.token = None
        self.expires_at = 0.0
        self.last_request = 0.0

    def product(self, ean: str):
        if time.monotonic() >= self.expires_at - 30:
            self.token, lifetime = authenticate(os.environ.get("BOL_API_CLIENT_ID"), os.environ.get("BOL_API_CLIENT_SECRET"))
            self.expires_at = time.monotonic() + lifetime
        delay = 1.05 - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()
        url = CATALOG_URL + urllib.parse.quote(ean) + "?" + urllib.parse.urlencode({
            "country-code": "NL", "include-specifications": "true"
        })
        try:
            return request_json(urllib.request.Request(url, headers={
                "Authorization": "Bearer " + self.token, "Accept": "application/json", "Accept-Language": "nl"
            }), "bol_metadata")
        except ReviewError as exc:
            if exc.status == 404:
                return None
            raise


def load_targets(conn, limit: int, cursor: str | None):
    if cursor:
        uuid.UUID(cursor)
    predicate = """(p.title ~* '^(vinyl|lp|record)( (ean|upc))? [0-9]{8,14}$'
      or p.title ~ '^[0-9]{8,14}$' or p.title ~* '^unknown( (album|title))?$' or btrim(p.title)='')"""
    params: list = []
    cursor_sql = ""
    if cursor:
        cursor_sql = "and p.id>%s::uuid"
        params.append(cursor)
    params.append(limit)
    rows = conn.execute(f"""select p.id::text,p.ean,p.gtin_normalized,p.artist,p.title,p.format_label,
      p.metadata_source,p.metadata_status,
      count(distinct pr.shop_id) filter(where pr.is_active and pr.last_seen_at>=now()-interval '48 hours')::int active_shops
      from products p left join prices pr on pr.product_id=p.id
      where {predicate} and p.ean is not null
        and coalesce(p.metadata_source,'') not in ('manual','verified')
        and coalesce(p.metadata_status,'') not in ('manual','verified') {cursor_sql}
      group by p.id
      order by p.id limit %s""", params).fetchall()
    remaining = conn.execute(
        f"select count(*)::int as count from products p where {predicate} and p.ean is not null"
    ).fetchone()["count"]
    return rows, remaining


def apply_one(conn, product: dict, metadata: dict) -> bool:
    result = conn.execute("""update products set artist=%s,title=%s,
      artist_normalized=lower(btrim(%s)),title_normalized=lower(btrim(%s)),
      search_text=lower(btrim(concat_ws(' ',%s,%s,ean,gtin_normalized))),
      metadata_source='bol_catalog_api',metadata_status='enriched',metadata_confidence=95,
      metadata_needs_review=false,metadata_last_enriched_at=now(),updated_at=now()
      where id=%s::uuid
        and (title ~* '^(vinyl|lp|record)( (ean|upc))? [0-9]{8,14}$'
          or title ~ '^[0-9]{8,14}$' or title ~* '^unknown( (album|title))?$' or btrim(title)='')
        and coalesce(metadata_source,'') not in ('manual','verified')
        and coalesce(metadata_status,'') not in ('manual','verified')""",
      (metadata["artist"], metadata["title"], metadata["artist"], metadata["title"],
       metadata["artist"], metadata["title"], product["id"])).rowcount
    return result == 1


def run(limit: int, write: bool, progress: Path = STATE_PATH):
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL is required")
    state = json.loads(progress.read_text()) if progress.exists() else {"country": "NL", "cursor": None}
    if state.get("country") != "NL":
        raise SystemExit("invalid checkpoint market")
    cursor = state.get("cursor")
    summary = {"status": "running", "write": write, "requested": limit, "checked": 0, "updated": 0,
               "skipped": {}, "cursor_start": cursor, "cursor_end": cursor, "items": []}
    client, skips = Client(), Counter()
    try:
        with psycopg.connect(dsn, row_factory=dict_row, prepare_threshold=None) as conn:
            products, remaining = load_targets(conn, limit, cursor)
            summary["remaining_at_start"] = remaining
            for product in products:
                summary["checked"] += 1
                summary["cursor_end"] = product["id"]
                try:
                    response = client.product(str(product["ean"]))
                    if response is None:
                        skips["not_found"] += 1
                        continue
                    metadata = normalize_response(product, response)
                    item = {"product_id": product["id"], "ean": product["ean"], "old_title": product["title"],
                            "artist": metadata["artist"], "title": metadata["title"]}
                    summary["items"].append(item)
                    if write and apply_one(conn, product, metadata):
                        conn.commit()
                        summary["updated"] += 1
                    else:
                        conn.rollback()
                except ValueError as exc:
                    conn.rollback(); skips[str(exc)] += 1
            summary["skipped"] = dict(skips)
            summary["status"] = "complete" if not products else "success"
            if write and products:
                progress.parent.mkdir(parents=True, exist_ok=True)
                progress.write_text(json.dumps({"country": "NL", "cursor": summary["cursor_end"],
                    "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n")
    except ReviewError as exc:
        summary["status"] = "blocked"
        summary["error"] = {"stage": exc.stage, "reason": exc.reason, "http_status": exc.status}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "items"}, ensure_ascii=False), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1500:
        raise SystemExit("limit must be 1-1500")
    summary = run(args.limit, args.write)
    return 0 if summary["status"] in {"success", "complete"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
