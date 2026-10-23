"""Bol Affiliate Entertainment feed. No network API or web scraping fallback.

The live v2 schema must be checked against the account's actual feed. Field
mapping is explicit; undocumented format/condition values never imply vinyl/new.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import ftplib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
from urllib.parse import urlencode, urlsplit, urlunsplit

from lxml import etree
import psycopg
from psycopg.types.json import Jsonb

from scripts.importers.common import (
    CanonicalRecord, _insert_product, identifier_candidates, strict_normalize_gtin,
    upsert_price, maybe_insert_history,
)

FEED_NAME = "product-feed_entertainment-v2.csv.gz"
FTP_HOST = "apm-feed.unftp.bol.com"
MARKETS = {"NL", "BE"}


class FeedError(ValueError):
    """A safe message, never a raw network/DB exception containing credentials."""


def amount(value, *, zero=False):
    text = str(value or "").strip()
    # Feed decimals, not page amounts. Never extract a number from prose.
    if not re.fullmatch(r"\d+(?:[.,]\d{1,2})?", text):
        raise FeedError("invalid_amount")
    try:
        price = Decimal(text.replace(",", "."))
    except InvalidOperation:
        raise FeedError("invalid_amount") from None
    if price < 0 or (price == 0 and not zero):
        raise FeedError("invalid_amount")
    return format(price.quantize(Decimal(".01")), "f")


def product_link(value, country):
    url = urlsplit(value)
    if (url.scheme != "https" or url.netloc not in {"www.bol.com", "bol.com"}
            or url.username or url.password or url.query or url.fragment
            or not re.fullmatch(r"/(?:nl|be)/(?:nl|fr)/p/[^/]+/\d+/", url.path)):
        raise FeedError("invalid_product_link")
    if url.path.split("/")[1] != country.lower():
        raise FeedError("wrong_destination_country")
    return urlunsplit(("https", "www.bol.com", url.path, "", ""))


def affiliate_link(value, country, site_id):
    if not re.fullmatch(r"\d+", site_id):
        raise FeedError("missing_or_invalid_site_id")
    return "https://partner.bol.com/click/click?" + urlencode({
        "p": "1", "t": "url", "s": site_id,
        "url": product_link(value, country), "f": "pf",
    })


@contextmanager
def text_feed(path):
    """Stream compressed bulk feeds; row and field limits bound parsing."""
    with open(path, "rb") as probe:
        compressed = probe.read(2) == b"\x1f\x8b"
    opener = gzip.open if compressed else open
    with opener(path, "rb") as raw:
        # Binary reads are bounded by the caller's row budget and gzip CRC is
        # checked on full imports. Partial pilots are always marked incomplete.
        with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
            yield stream


def rows_from(path, profile):
    kind = profile.get("type", "csv")
    if kind == "csv":
        csv.field_size_limit(1_000_000)
        with text_feed(path) as stream:
            reader = csv.DictReader(stream, delimiter="|", strict=True)
            headers = reader.fieldnames or []
            required = {profile[k] for k in ["ean", "product_id", "title", "format"]}
            if len(headers) != len(set(headers)) or not required.issubset(headers):
                raise FeedError("missing_or_duplicate_feed_headers")
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise FeedError("malformed_feed_row")
                yield row
    elif kind == "xml":
        # lxml streaming with network, DTD expansion and entities disabled.
        with open(path, "rb") as probe:
            compressed = probe.read(2) == b"\x1f\x8b"
        with (gzip.open(path, "rb") if compressed else open(path, "rb")) as stream:
            context = etree.iterparse(stream, events=("end",), resolve_entities=False,
                                      no_network=True, load_dtd=False, huge_tree=False)
            for _, element in context:
                if etree.QName(element).localname != "Product":
                    continue
                row = {}

                def flatten(node, prefix=""):
                    for child in node:
                        if not isinstance(child.tag, str):
                            raise FeedError("xml_entities_not_supported")
                        name = etree.QName(child).localname
                        key = prefix + name
                        if name == "Properties":
                            for prop in child:
                                parts = {etree.QName(c).localname: c.text or "" for c in prop}
                                if parts.get("key"):
                                    row["Properties." + parts["key"]] = parts.get("value", "")
                        elif len(child):
                            flatten(child, key + ".")
                        else:
                            row[key] = child.text or ""
                flatten(element)
                yield row
                element.clear()
                while element.getprevious() is not None:
                    del element.getparent()[0]
    else:
        raise FeedError("unsupported_feed_type")


def select_product(row, profile, countries, site_id, captured_at):
    """Select only explicit new vinyl; never borrow another market's offer."""
    ean = row.get(profile["ean"], "").strip()
    gtin = strict_normalize_gtin(ean) if re.fullmatch(r"\d{8}|\d{12,14}", ean) else None
    if not gtin:
        raise FeedError("missing_or_invalid_barcode")
    medium = row.get(profile["format"], "").strip().casefold()
    if medium not in {str(v).casefold() for v in profile["vinyl_values"]}:
        raise FeedError("format_not_proven_vinyl")
    product_id = row.get(profile["product_id"], "").strip()
    title = row.get(profile["title"], "").strip()
    if not product_id or not title:
        raise FeedError("missing_product_identity_or_title")
    offers, skipped = [], []
    for country in countries:
        fields = profile["offers"][country]
        get = lambda key: row.get(fields.get(key, ""), "").strip()
        if not get("price"):
            skipped.append({"ean": ean, "title": title, "country": country, "reason": "no_market_offer"})
            continue
        if get("condition").casefold() not in {str(v).casefold() for v in profile["new_values"]}:
            skipped.append({"ean": ean, "title": title, "country": country, "reason": "condition_not_proven_new"})
            continue
        try:
            price = amount(get("price"))  # sellingPrice is payable; listPrice isn't.
            link = affiliate_link(get("url"), country, site_id)
            shipping = amount(get("shipping"), zero=True) if get("shipping") else None
        except FeedError as exc:
            skipped.append({"ean": ean, "title": title, "country": country, "reason": str(exc)})
            continue
        deliverable = get("deliverable").casefold()
        availability = {"true": "in_stock", "1": "in_stock", "false": "out_of_stock",
                        "0": "out_of_stock"}.get(deliverable, "unknown")
        offers.append({"ean": ean, "gtin": gtin, "product_id": product_id,
                       "title": title, "country": country, "price": price, "currency": "EUR",
                       "availability": availability,
                       "seller": {"B": "bol", "P": "external_partner"}.get(get("seller_type"), "unknown"),
                       "shipping": shipping, "shipping_status": "known" if shipping is not None else "unknown",
                       "product_url": link, "captured_at": captured_at.isoformat()})
    return offers, skipped


def build_plan(path, profile, countries, site_id, *, limit=20, max_rows=1_000_000,
               captured_at=None):
    if not countries or not set(countries).issubset(MARKETS):
        raise FeedError("unsupported_market")
    if len(set(countries)) != len(countries) or limit < 0 or max_rows < 1:
        raise FeedError("invalid_limits_or_duplicate_markets")
    captured_at = captured_at or datetime.now(timezone.utc)
    accepted, ambiguous, reasons, samples = {}, set(), Counter(), []
    products, read, exhausted = set(), 0, False
    iterator = iter(rows_from(path, profile))
    for row in iterator:
        read += 1
        try:
            offers, skips = select_product(row, profile, countries, site_id, captured_at)
            for skip in skips:
                reasons[skip["reason"]] += 1
                if len(samples) < 20:
                    samples.append(skip)
            for offer in offers:
                key = (offer["gtin"], offer["country"])
                if key in ambiguous:
                    continue
                previous = accepted.get(key)
                if previous and any(previous[k] != offer[k] for k in
                                    ["price", "availability", "product_url", "shipping", "seller"]):
                    ambiguous.add(key)
                    del accepted[key]
                    reasons["conflicting_offer_for_barcode_market"] += 1
                    continue
                accepted[key] = offer
                products.add(offer["gtin"])
        except FeedError as exc:
            reasons[str(exc)] += 1
            if len(samples) < 20:
                samples.append({"row": read, "reason": str(exc)})
        if (limit and len(products) >= limit) or read >= max_rows:
            break
    else:
        exhausted = True
    iterator.close()
    return {"source": "bol_affiliate_productfeed", "read_products": read,
            "selected_new_vinyl": len({o["gtin"] for o in accepted.values()}),
            "valid_barcodes": len({o["gtin"] for o in accepted.values()}),
            "complete_feed": exhausted, "database_writes": 0,
            "existing_matches": None, "new_products": None,
            "match_status": "not_checked_no_database", "skipped": dict(reasons),
            "skip_samples": samples, "offers": list(accepted.values()),
            "captured_at": captured_at.isoformat(), "errors": [],
            "music_content_attribution": "© Muze UK Ltd"}


def find_product(cur, offer):
    ids = identifier_candidates(offer["ean"], offer["gtin"])
    cur.execute("""select id,format_label from public.products
                   where ean=any(%s) or gtin_normalized=any(%s)""", (ids, ids))
    rows = cur.fetchall()
    if len(rows) > 1:
        raise FeedError("ambiguous_existing_barcode")
    if rows and str(rows[0][1] or "").strip().casefold() in {
            "cd", "dvd", "bluray", "blu-ray", "accessories", "poster", "digital"}:
        raise FeedError("existing_product_format_conflict")
    return rows[0][0] if rows else None


def review_matches(plan, dsn):
    existing, new, rejected = set(), set(), []
    with psycopg.connect(dsn, prepare_threshold=None) as conn:
        conn.execute("set transaction read only")
        with conn.cursor() as cur:
            for offer in plan["offers"]:
                try:
                    target = find_product(cur, offer)
                except FeedError as exc:
                    rejected.append({"ean": offer["ean"], "country": offer["country"], "reason": str(exc)})
                    continue
                (existing if target else new).add(offer["gtin"])
    plan.update(existing_matches=len(existing), new_products=len(new),
                match_status="read_only_checked", match_conflicts=rejected)


def publish(plan, dsn, shops, approved=False, existing_only=False):
    """One transaction for all selected markets; never registers/activates shops.

    No shared bol titles/covers/descriptions are published. New barcode products
    use a neutral placeholder, via the existing importer insertion contract.
    """
    if not approved:
        raise FeedError("public_import_requires_explicit_approval")
    if plan["errors"] or not plan["offers"]:
        raise FeedError("empty_or_failed_plan")
    captured = datetime.fromisoformat(plan["captured_at"])
    if not captured.tzinfo or not 0 <= (datetime.now(timezone.utc) - captured).total_seconds() <= 21600:
        raise FeedError("stale_or_future_feed")
    stats = {"new_products": 0, "updated_offers": 0, "skipped_newer": 0, "verified": 0}
    written = []
    with psycopg.connect(dsn, prepare_threshold=None) as conn, conn.cursor() as cur:
        # Shared lock across countries prevents two imports splitting NL/BE.
        cur.execute("select pg_advisory_xact_lock(hashtextextended('bol-affiliate-import',0))")
        for country in sorted({o["country"] for o in plan["offers"]}):
            if country not in shops:
                raise FeedError("missing_market_shop_configuration")
            cur.execute("select country,name from public.shops where id=%s", (shops[country],))
            row = cur.fetchone()
            if not row or row[0] != country or not re.match(r"^bol(?:\b|[ .(])", row[1], re.I):
                raise FeedError("invalid_market_shop")
            cur.execute("""select country_code,status from public.shop_shipping_destinations
                           where shop_id=%s""", (shops[country],))
            destinations = cur.fetchall()
            if any(m != country and state == "confirmed" for m, state in destinations):
                raise FeedError("cross_market_shop_exposure")
        if len(set(shops.values())) != len(shops):
            raise FeedError("markets_must_use_distinct_shops")
        for offer in sorted(plan["offers"], key=lambda o: (o["gtin"], o["country"])):
            cur.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (offer["gtin"],))
            product_id = find_product(cur, offer)
            record = CanonicalRecord(
                source_row_number=0, shop_name="bol " + offer["country"], shop_domain="bol.com",
                shop_country=offer["country"], ean=offer["ean"], gtin_normalized=offer["gtin"],
                artist="", title="Vinyl " + offer["ean"], format_label="Vinyl", cover_url=None,
                product_url=offer["product_url"], price=Decimal(offer["price"]), currency="EUR",
                availability=offer["availability"], captured_at=captured, product_handle=None,
                detail_status="ok", is_secondhand=False, raw={})
            if product_id is None and existing_only:
                raise FeedError('existing_product_required')
            if product_id is None:
                # Savepoint handles a concurrent non-bol importer winning EAN.
                cur.execute("savepoint bol_new_product")
                try:
                    product_id = _insert_product(cur, record)
                    stats["new_products"] += 1
                except psycopg.errors.UniqueViolation:
                    cur.execute("rollback to savepoint bol_new_product")
                    product_id = find_product(cur, offer)
                    if product_id is None:
                        raise FeedError("product_identity_conflict") from None
                cur.execute("release savepoint bol_new_product")
            shop_id = shops[offer["country"]]
            cur.execute("""select last_seen_at from public.prices
                           where product_id=%s and shop_id=%s for update""", (product_id, shop_id))
            old = cur.fetchone()
            if old and old[0] and old[0] > captured:
                stats["skipped_newer"] += 1
                continue
            # Repeat of the same snapshot makes no price/history/content writes.
            digest = hashlib.sha256(json.dumps(offer, sort_keys=True).encode()).hexdigest()
            cur.execute("""select 1 from public.raw_shop_scrapes where shop_id=%s
                           and source_product_id=%s and payload->>'bol_import_digest'=%s limit 1""",
                        (str(shop_id), offer["product_id"], digest))
            if cur.fetchone():
                continue
            upsert_price(cur, str(product_id), shop_id, record, captured)
            maybe_insert_history(cur, str(product_id), shop_id, record)
            cur.execute("""insert into public.raw_shop_scrapes
                (shop_id,source_url,source_product_id,title_raw,ean_raw,price_raw,
                 availability_raw,payload,scraped_at,parse_status)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'bol_affiliate_evidence')""",
                        (str(shop_id), offer["product_url"], offer["product_id"], offer["title"],
                         offer["ean"], offer["price"], offer["availability"],
                         Jsonb({**offer, "bol_import_digest": digest}), captured))
            written.append((str(product_id), shop_id, Decimal(offer["price"]), offer["product_url"]))
            stats["updated_offers"] += 1
        for product_id, shop_id, price, url in written:
            cur.execute("select price,product_url from public.prices where product_id=%s and shop_id=%s",
                        (product_id, shop_id))
            if cur.fetchone() != (price, url):
                raise FeedError("price_postcondition_failed")
            stats["verified"] += 1
    # A context exit commits only after every market passes its postconditions.
    with psycopg.connect(dsn, prepare_threshold=None) as conn, conn.cursor() as cur:
        cur.execute("set transaction read only")
        for product_id, shop_id, price, url in written:
            cur.execute("select price,product_url from public.prices where product_id=%s and shop_id=%s",
                        (product_id, shop_id))
            if cur.fetchone() != (price, url):
                raise FeedError("committed_price_verification_failed")
    stats["committed_verified"] = len(written)
    return stats


def download_feed(destination, *, max_bytes=2_000_000_000):
    """Explicit FTPS, verified certificates, passive TLS data. No secret URL."""
    user, password = os.environ.get("BOL_FEED_USERNAME"), os.environ.get("BOL_FEED_PASSWORD")
    if not user or not password:
        raise FeedError("missing_feed_credentials")
    size = 0
    destination = Path(destination)
    stage = "connect"
    try:
        with ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=60) as ftp:
            ftp.connect(FTP_HOST, 21)
            stage = "tls_auth"
            ftp.auth()
            stage = "login"
            ftp.login(user, password)
            stage = "protect_data"
            ftp.prot_p()
            stage = "passive_mode"
            ftp.set_pasv(True)
            stage = "feed_timestamp"
            modified = ftp.sendcmd("MDTM " + FEED_NAME).split()[-1]
            source_at = datetime.strptime(modified, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            stage = "download"
            with destination.open("wb") as target:
                def receive(block):
                    nonlocal size
                    size += len(block)
                    if size > max_bytes:
                        raise FeedError("feed_download_size_limit")
                    target.write(block)
                ftp.retrbinary("RETR " + FEED_NAME, receive)
            stage = "close"
    except Exception as exc:
        destination.unlink(missing_ok=True)
        if isinstance(exc, FeedError):
            raise
        # FTP replies and OS messages may contain account names or paths.
        # Report only our stage, a fixed category, and a numeric FTP status.
        reason = ("certificate_verification" if isinstance(exc, ssl.SSLCertVerificationError)
                  else "tls_error" if isinstance(exc, ssl.SSLError)
                  else "ftp_rejected" if isinstance(exc, ftplib.error_perm)
                  else "ftp_temporary_error" if isinstance(exc, ftplib.error_temp)
                  else "timeout" if isinstance(exc, TimeoutError)
                  else "network_or_local_io" if isinstance(exc, OSError)
                  else "invalid_server_reply" if isinstance(exc, ValueError)
                  else "unexpected_error")
        status = re.match(r"^([45][0-9]{2})(?:[ -]|$)", str(exc)) if isinstance(exc, ftplib.Error) else None
        code = f" ftp_status={status[1]}" if status else ""
        raise FeedError(f"feed_download_failed stage={stage} reason={reason}{code}") from None
    if not size:
        destination.unlink(missing_ok=True)
        raise FeedError("empty_feed_download")
    return source_at


def inspect_schema(path, profile):
    """Inspect headers/format vocabularies without exporting bulk content."""
    if profile.get("type", "csv") == "csv":
        with text_feed(path) as stream:
            reader = csv.DictReader(stream, delimiter="|", strict=True)
            headers = reader.fieldnames or []
            samples = []
            for _, row in zip(range(20), reader):
                samples.append({k: v for k, v in row.items() if k and re.search(
                    r"format|drager|condition|sellerType|category|gpc", k, re.I)})
    else:
        iterator = rows_from(path, profile)
        samples = []
        headers = set()
        for _, row in zip(range(20), iterator):
            headers.update(row)
            samples.append({k: v for k, v in row.items() if re.search(
                r"format|drager|condition|sellerType|category|gpc", k, re.I)})
        iterator.close()
        headers = sorted(headers)
    if not headers:
        raise FeedError("empty_feed_schema")
    return {"status": "schema_inspected", "database_writes": 0, "errors": [],
            "headers": headers, "field_samples": samples,
            "offers": [], "live_schema_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, help="Local CSV/XML(.gz); otherwise fetch FTPS")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--markets", default="NL,BE")
    parser.add_argument("--limit", type=int, default=20, help="Selected products; 0=full bounded scan")
    parser.add_argument("--max-rows", type=int, default=1_000_000)
    parser.add_argument("--source-at", help="Local feed generation timestamp, ISO8601 with timezone")
    parser.add_argument("--output", type=Path, default=Path("output/bol/review.json"))
    parser.add_argument("--check-matches", action="store_true")
    parser.add_argument("--inspect-schema", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--approve-publication", action="store_true")
    args = parser.parse_args(argv)
    report = {"status": "blocked", "database_writes": 0, "errors": []}
    try:
        profile = json.loads(args.profile.read_text())
        if args.write and (not args.approve_publication or not profile.get("live_schema_verified")):
            raise FeedError("approve_publication_and_verified_live_schema_required")
        with tempfile.TemporaryDirectory(prefix="bol-feed-") as directory:
            path = args.feed or Path(directory) / FEED_NAME
            source_at = datetime.fromisoformat(args.source_at) if args.source_at else None
            if not args.feed:
                source_at = download_feed(path)
            if args.write and source_at is None:
                raise FeedError("local_write_requires_proven_source_timestamp")
            if args.inspect_schema:
                if args.write or args.check_matches:
                    raise FeedError("schema_inspection_cannot_write_or_query_database")
                report = inspect_schema(path, profile)
            else:
                report = build_plan(path, profile, args.markets.split(","), os.environ.get("BOL_SITE_ID", ""),
                                    limit=args.limit, max_rows=args.max_rows, captured_at=source_at)
            report["source_timestamp_status"] = "provided_or_ftp_mdtm" if source_at else "unknown_dry_run_only"
            report["feed_sha256"] = file_digest(path)
            if not args.inspect_schema:
                report["status"] = "dry_run" if report["offers"] else "no_eligible_offers"
            if args.check_matches:
                review_matches(report, os.environ["DATABASE_URL"])
            if args.write:
                shops = json.loads(os.environ.get("BOL_SHOP_IDS", "{}"))
                result = publish(report, os.environ["DATABASE_URL"], shops, approved=True)
                report["write_result"] = result
                report["database_writes"] = result["updated_offers"]
                report["status"] = "written"
    except Exception as exc:
        # Never echo driver messages, secret paths/URLs or traceback.
        report["status"] = "blocked"
        report["errors"] = [str(exc) if isinstance(exc, FeedError) else type(exc).__name__]
        if args.write:
            # Commit can be ambiguous on connection loss; never assert zero.
            report["database_writes"] = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in {"offers", "skip_samples"}}))
    return 1 if report["errors"] or (not report.get("offers") and report["status"] != "schema_inspected") else 0


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
