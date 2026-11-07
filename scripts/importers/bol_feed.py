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
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

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
            if not product_id.isascii() or not product_id.isdigit() or urlsplit(
                    product_link(get("url"), country)).path.rstrip("/").rsplit("/", 1)[-1] != product_id:
                raise FeedError("product_identity_link_mismatch")
            link = affiliate_link(get("url"), country, site_id)
            shipping = amount(get("shipping"), zero=True) if get("shipping") else None
        except FeedError as exc:
            skipped.append({"ean": ean, "title": title, "country": country, "reason": str(exc)})
            continue
        deliverable = get("deliverable").casefold()
        availability = {k.casefold(): v for k, v in profile.get("availability_values", {
            "true": "in_stock", "1": "in_stock", "false": "out_of_stock", "0": "out_of_stock"
        }).items()}.get(deliverable, "unknown")
        release_date = get("release_date")
        if release_date and availability == "in_stock":
            try:
                released = datetime.strptime(release_date, "%Y-%m-%d").date()
            except ValueError:
                availability = "unknown"
            else:
                if released > captured_at.date():
                    # Deliverable preorders are not proof of current stock.
                    # Preserve evidence; do not invent an API preorder flag.
                    availability = "unknown"
        offers.append({"ean": ean, "gtin": gtin, "product_id": product_id,
                       "title": title, "country": country, "price": price, "currency": "EUR",
                       "availability": availability, "release_date": release_date or None,
                       "seller": {"B": "bol", "P": "external_partner"}.get(get("seller_type"), "unknown"),
                       "shipping": shipping, "shipping_status": "known" if shipping is not None else "unknown",
                       "product_url": link, "captured_at": captured_at.isoformat()})
    return offers, skipped


def build_plan(path, profile, countries, site_id, *, limit=20, max_rows=1_000_000,
               captured_at=None, audit_gtins=None):
    if not countries or not set(countries).issubset(MARKETS):
        raise FeedError("unsupported_market")
    if len(set(countries)) != len(countries) or limit < 0 or max_rows < 1:
        raise FeedError("invalid_limits_or_duplicate_markets")
    captured_at = captured_at or datetime.now(timezone.utc)
    accepted, ambiguous, reasons, samples = {}, set(), Counter(), []
    audited_seen, source_rejections = set(), []
    audit_gtins = set(audit_gtins or [])
    products, read, exhausted = set(), 0, False
    iterator = iter(rows_from(path, profile))
    for row in iterator:
        read += 1
        audit_gtin = strict_normalize_gtin(row.get(profile["ean"], ""))
        if audit_gtin in audit_gtins:
            audited_seen.add(audit_gtin)
        rejection = None
        try:
            offers, skips = select_product(row, profile, countries, site_id, captured_at)
            if audit_gtin in audit_gtins and not any(o["country"] == "NL" for o in offers):
                rejection = next((v["reason"] for v in skips if v["country"] == "NL"), "no_selected_nl_offer")
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
                if previous:
                    reasons["identical_duplicate_offer"] += 1
                accepted[key] = offer
                products.add(offer["gtin"])
        except FeedError as exc:
            rejection = str(exc)
            reasons[str(exc)] += 1
            if len(samples) < 20:
                samples.append({"row": read, "reason": str(exc)})
        if audit_gtin in audit_gtins and rejection:
            fields = profile["offers"].get("NL", {})
            source_rejections.append({"gtin": audit_gtin, "reason": rejection,
                "source_product_id": row.get(profile["product_id"]),
                "format": row.get(profile["format"]),
                "category_subgroup": row.get("Category.subgroup"),
                "category_subsubgroup": row.get("Category.subssubgroup"),
                "condition": row.get(fields.get("condition", "")),
                "selling_price": row.get(fields.get("price", "")),
                "deliverable": row.get(fields.get("deliverable", "")),
                "release_date": row.get(fields.get("release_date", ""))})
        if (limit and len(products) >= limit) or read >= max_rows:
            break
    else:
        exhausted = True
    iterator.close()
    market_summary = {}
    for country in countries:
        offers = [o for o in accepted.values() if o["country"] == country]
        market_summary[country] = {
            "selected_new_vinyl": len({o["gtin"] for o in offers}), "valid_prices": len(offers),
            "availability": dict(Counter(o["availability"] for o in offers)),
            "shipping": dict(Counter(o["shipping_status"] for o in offers)),
            "seller": dict(Counter(o["seller"] for o in offers)),
        }
    return {"source": "bol_affiliate_productfeed", "read_products": read,
            "markets": market_summary,
            "coverage_source_rejections": source_rejections,
            "coverage_source_absent_gtins": sorted(audit_gtins - audited_seen),
            "coverage_source_targets": len(audit_gtins),
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


def review_matches(plan, dsn, shops=None, *, batch_size=500):
    """Consistent read-only batches; report identity conflicts and price deltas."""
    shops = shops or {}
    existing, new, rejected = set(), set(), []
    comparisons = Counter()
    coverage = {}
    matched_by_market = {country: set() for country in shops}
    grouped = {}
    for offer in plan["offers"]:
        grouped.setdefault(offer["gtin"], []).append(offer)
    keys = sorted(grouped)
    with psycopg.connect(dsn, prepare_threshold=None) as conn:
        conn.execute("set transaction isolation level repeatable read read only")
        with conn.cursor() as cur:
            for offset in range(0, len(keys), batch_size):
                batch = keys[offset:offset + batch_size]
                variants = {g: set().union(*(set(identifier_candidates(o["ean"], g))
                            for o in grouped[g])) for g in batch}
                ids = sorted(set().union(*variants.values()))
                cur.execute("""select id,format_label,ean,gtin_normalized from public.products
                               where ean=any(%s) or gtin_normalized=any(%s)""", (ids, ids))
                rows = cur.fetchall()
                lookup = {}
                for row in rows:
                    for value in {row[2], row[3]} - {None}:
                        lookup.setdefault(value, {})[str(row[0])] = row
                matched = {}
                for gtin in batch:
                    found = {pid: row for v in variants[gtin]
                             for pid, row in lookup.get(v, {}).items()}
                    reason = None
                    if len(found) > 1:
                        reason = "ambiguous_existing_barcode"
                    elif found:
                        row = next(iter(found.values()))
                        if str(row[1] or "").strip().casefold() in {
                                "cd", "dvd", "bluray", "blu-ray", "accessories", "poster", "digital"}:
                            reason = "existing_product_format_conflict"
                        else:
                            matched[gtin] = str(row[0]); existing.add(gtin)
                    else:
                        new.add(gtin)
                    if reason:
                        rejected.append({"gtin": gtin, "reason": reason})
                prices = {}
                if matched and shops:
                    cur.execute("""select product_id,shop_id,price,last_seen_at,availability
                                   from public.prices where product_id=any(%s::uuid[])
                                   and shop_id=any(%s::uuid[])""",
                                (list(matched.values()), list(shops.values())))
                    prices = {(str(r[0]), str(r[1])): r[2:] for r in cur.fetchall()}
                for gtin, pid in matched.items():
                    for offer in grouped[gtin]:
                        if offer["country"] in matched_by_market:
                            matched_by_market[offer["country"]].add(pid)
                        shop = shops.get(offer["country"])
                        if not shop:
                            comparisons["market_shop_not_configured"] += 1; continue
                        old = prices.get((pid, str(shop)))
                        if old is None:
                            comparisons["new_shop_offer"] += 1
                        else:
                            comparisons["unchanged_price" if old[0] == Decimal(offer["price"])
                                        else "changed_price"] += 1
                            if old[1] and old[1] > datetime.fromisoformat(offer["captured_at"]):
                                comparisons["newer_database_price"] += 1
            if plan.get("complete_feed"):
                for country, shop_id in shops.items():
                    if country not in plan.get("markets", {}):
                        continue
                    cur.execute("select product_id from public.prices where shop_id=%s and is_active=true", (shop_id,))
                    active = {str(row[0]) for row in cur.fetchall()}
                    missing = active - matched_by_market[country]
                    coverage[country] = {"existing_active_shop_offers": len(active),
                                         "covered_by_feed": len(active - missing),
                                         "absent_from_eligible_feed": len(missing),
                                         "absent_product_samples": sorted(missing)[:20]}
    plan["existing_offer_coverage"] = coverage
    for country, summary in plan.get("markets", {}).items():
        gtins = {o["gtin"] for o in plan["offers"] if o["country"] == country}
        summary.update(existing_matches=len(gtins & existing), new_products=len(gtins & new))
    plan.update(existing_matches=len(existing), new_products=len(new),
                match_status="read_only_checked", match_conflicts=rejected,
                price_comparisons=dict(comparisons), match_batch_size=batch_size)


def load_coverage_gtins(dsn, shops):
    with psycopg.connect(dsn, prepare_threshold=None) as conn, conn.cursor() as cur:
        cur.execute("set transaction read only")
        cur.execute("""select p.ean,p.gtin_normalized from public.products p
                       join public.prices pr on pr.product_id=p.id
                       where pr.shop_id=any(%s::uuid[]) and pr.is_active=true""", (list(shops.values()),))
        return {g for row in cur.fetchall() for value in row
                if (g := strict_normalize_gtin(value))}


def quarantine_identity_conflicts(plan):
    """Exclude unsafe GTINs from this source; never repair canonical metadata."""
    conflicts = plan.get("match_conflicts", [])
    if any(c["reason"] not in {"ambiguous_existing_barcode", "existing_product_format_conflict"}
           for c in conflicts):
        raise FeedError("unclassified_database_conflict")
    if not conflicts:
        return
    blocked = {c["gtin"] for c in conflicts}
    before = len(plan["offers"])
    plan["offers"] = [o for o in plan["offers"] if o["gtin"] not in blocked]
    plan["quarantined_identity_conflicts"] = conflicts
    plan["quarantined_offers"] = before - len(plan["offers"])
    plan["match_conflicts"] = []
    plan["selected_new_vinyl"] = len({o["gtin"] for o in plan["offers"]})
    plan["valid_barcodes"] = plan["selected_new_vinyl"]
    plan["valid_prices"] = len(plan["offers"])
    for country, summary in plan.get("markets", {}).items():
        offers = [o for o in plan["offers"] if o["country"] == country]
        summary.update(selected_new_vinyl=len({o["gtin"] for o in offers}),valid_prices=len(offers),
                       availability=dict(Counter(o["availability"] for o in offers)),
                       shipping=dict(Counter(o["shipping_status"] for o in offers)),
                       seller=dict(Counter(o["seller"] for o in offers)))


class SafeWriterCursor:
    """Report timeout stage without leaking SQL parameters or driver messages."""
    def __init__(self, cursor):
        self.cursor = cursor

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def execute(self, statement, params=None):
        query = str(statement).lower()
        stage = "writer_statement"
        if "pg_advisory_xact_lock" in query:
            stage = "source_lock" if "bol-affiliate-import" in query else "barcode_lock"
        else:
            for table in ("raw_shop_scrapes", "price_history", "products", "prices", "shops", "shop_shipping_destinations"):
                if "public." + table in query:
                    stage = table + ("_write" if "insert into" in query else "_read")
                    break
        try:
            return self.cursor.execute(statement, params)
        except psycopg.errors.QueryCanceled:
            raise FeedError("database_statement_timeout stage=" + stage) from None


def reviewed_pilot(path, expected_digest, site_id):
    """Validate a trusted workflow's cached selection; never expand its scope."""
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_digest or "")
            or report.get("feed_sha256") != expected_digest):
        raise FeedError("reviewed_feed_checksum_mismatch")
    if (report.get("source") != "bol_affiliate_productfeed" or report.get("complete_feed")
            or report.get("status") not in {"dry_run", "blocked", "written"}
            or any(error != "QueryCanceled" and not error.startswith("database_statement_timeout stage=")
                   for error in report.get("errors", []))):
        raise FeedError("unsupported_reviewed_pilot_report")
    offers = report.get("offers", [])
    if not 1 <= len(offers) <= 20 or len({o["gtin"] for o in offers}) != len(offers):
        raise FeedError("reviewed_pilot_requires_at_most_twenty_unique_products")
    for offer in offers:
        if (offer["country"] != "NL" or offer.get("currency") != "EUR"
                or strict_normalize_gtin(offer["ean"]) != offer["gtin"]
                or offer["captured_at"] != report["captured_at"]
                or offer["availability"] not in {"in_stock", "out_of_stock", "unknown"}):
            raise FeedError("invalid_reviewed_pilot_identity_or_market")
        amount(offer["price"])
        if offer.get("shipping") is not None:
            amount(offer["shipping"], zero=True)
        query = parse_qs(urlsplit(offer["product_url"]).query, strict_parsing=True)
        destinations = query.get("url", [])
        if (len(destinations) != 1
                or affiliate_link(destinations[0], "NL", site_id) != offer["product_url"]
                or urlsplit(destinations[0]).path.rstrip("/").rsplit("/", 1)[-1] != offer["product_id"]):
            raise FeedError("invalid_reviewed_pilot_affiliate_link")
    report["previous_attempt_errors"] = report.get("errors", [])
    report.update(errors=[], database_writes=0, status="reviewed_pilot_ready",
                  reviewed_selection_sha256=file_digest(path))
    return report


def writer_diagnostics(dsn):
    """Read-only operational/schema evidence; no credentials, query text or writes."""
    with psycopg.connect(dsn, prepare_threshold=None) as conn, conn.cursor() as cur:
        cur.execute("set transaction read only")
        cur.execute("show statement_timeout")
        timeout = cur.fetchone()[0]
        cur.execute("show lock_timeout")
        lock_timeout = cur.fetchone()[0]
        cur.execute("""select locktype,mode,granted,count(*) from pg_locks
                       where locktype='advisory' group by locktype,mode,granted""")
        locks = cur.fetchall()
        cur.execute("""select tablename,indexname,indexdef from pg_indexes
                       where schemaname='public' and tablename=any(%s)
                       order by tablename,indexname""", (["products", "raw_shop_scrapes", "prices", "price_history"],))
        indexes = cur.fetchall()
        cur.execute("""select relname,n_live_tup,n_dead_tup from pg_stat_user_tables
                       where schemaname='public' and relname=any(%s)""",
                    (["products", "raw_shop_scrapes", "prices", "price_history"],))
        sizes = cur.fetchall()
        cur.execute("""select c.relname,t.tgname,p.proname
                       from pg_trigger t join pg_class c on c.oid=t.tgrelid
                       join pg_namespace n on n.oid=c.relnamespace join pg_proc p on p.oid=t.tgfoid
                       where n.nspname='public' and not t.tgisinternal
                       and c.relname=any(%s) order by c.relname,t.tgname""",
                    (["products", "raw_shop_scrapes", "prices", "price_history"],))
        triggers = cur.fetchall()
        cur.execute("""select state,wait_event_type,wait_event,count(*) from pg_stat_activity
                       where datname=current_database() group by state,wait_event_type,wait_event""")
        activity = cur.fetchall()
        cur.execute("""explain select 1 from public.raw_shop_scrapes where shop_id=%s
                       and source_product_id=%s and payload->>'bol_import_digest'=%s limit 1""",
                    ("f08437c2-1d85-47a6-94f9-33a55612d5cc", "9300000332934928", "diagnostic_nonexistent_digest"))
        replay_plan = [r[0] for r in cur.fetchall()]
        cur.execute("""explain select id,format_label from public.products
                       where ean=any(%s) or gtin_normalized=any(%s)""",
                    (["9101389353587"], ["09101389353587"]))
        product_plan = [r[0] for r in cur.fetchall()]
    return {"status": "writer_diagnosed", "database_writes": 0, "errors": [],
            "statement_timeout": timeout, "lock_timeout": lock_timeout,
            "advisory_locks": locks, "indexes": indexes, "table_estimates": sizes, "triggers": triggers, "activity": activity,
            "replay_lookup_plan": replay_plan, "product_lookup_plan": product_plan}


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
        cur = SafeWriterCursor(cur)
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
            # History records changes, including across calendar-day boundaries.
            cur.execute("""select price,availability from public.price_history
                           where product_id=%s and shop_id=%s
                           order by captured_at desc limit 1""", (product_id, shop_id))
            latest_history = cur.fetchone()
            if latest_history != (record.price, record.availability):
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


def _download_feed_once(destination, *, max_bytes=2_000_000_000, unchanged_since=None):
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
            if unchanged_since is not None and source_at == unchanged_since:
                age = (datetime.now(timezone.utc) - source_at).total_seconds()
                if not 0 <= age <= 21600:
                    raise FeedError("stale_or_future_feed")
                return source_at
            stage = "download"
            with destination.open("wb") as target:
                def receive(block):
                    nonlocal size
                    size += len(block)
                    if size > max_bytes:
                        raise FeedError("feed_download_size_limit")
                    target.write(block)
                ftp.retrbinary("RETR " + FEED_NAME, receive)
            stage = "verify_source_timestamp"
            if ftp.sendcmd("MDTM " + FEED_NAME).split()[-1] != modified:
                raise FeedError("feed_changed_during_download")
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


def download_feed(destination, *, max_bytes=2_000_000_000, attempts=3, unchanged_since=None):
    """Retry only transient transfers; never retry credentials/certificate errors."""
    for attempt in range(attempts):
        try:
            return _download_feed_once(destination, max_bytes=max_bytes, unchanged_since=unchanged_since)
        except FeedError as exc:
            transient = any(reason in str(exc) for reason in (
                "reason=timeout", "reason=network_or_local_io", "reason=ftp_temporary_error",
                "feed_changed_during_download"))
            if not transient or attempt + 1 >= attempts:
                raise
            time.sleep(2 ** attempt)


def verify_integrity(path, *, max_uncompressed_bytes=20_000_000_000):
    """Verify the entire gzip trailer even for a bounded pilot; no DB access."""
    with open(path, "rb") as probe:
        compressed = probe.read(2) == b"\x1f\x8b"
    count = 0
    with (gzip.open(path, "rb") if compressed else open(path, "rb")) as stream:
        while block := stream.read(1_048_576):
            count += len(block)
            if count > max_uncompressed_bytes:
                raise FeedError("feed_uncompressed_size_limit")
    return {"compressed_bytes": Path(path).stat().st_size,
            "uncompressed_bytes": count, "integrity": "verified_full_read"}


def inspect_schema(path, profile, *, max_rows=1_000_000):
    """Scan vocabulary and bounded candidate evidence; never infer a live mapping.

    Candidate detection is diagnostic only. It cannot approve or publish offers.
    Full traversal checks gzip CRC, unlike a twenty-row schema preview.
    """
    vocabulary = {}
    samples, candidates = [], []
    read, complete = 0, False
    csv.field_size_limit(1_000_000)
    with text_feed(path) as stream:
        if profile.get("type", "csv") != "csv":
            raise FeedError("full_schema_inspection_requires_csv")
        reader = csv.DictReader(stream, delimiter="|", strict=True)
        headers = reader.fieldnames or []
        if not headers or len(headers) != len(set(headers)):
            raise FeedError("missing_or_duplicate_feed_headers")
        diagnostic = [k for k in headers if re.search(
            r"format|drager|condition|sellerType|category|gpc|isDeliverable", k, re.I)]
        for row in reader:
            read += 1
            if None in row or any(v is None for v in row.values()):
                raise FeedError("malformed_feed_row")
            for k in diagnostic:
                counts = vocabulary.setdefault(k, Counter())
                value = row[k]
                # Bound diagnostics even if a source unexpectedly changes type.
                if value in counts or len(counts) < 200:
                    counts[value] += 1
                else:
                    counts["__other_values__"] += 1
            if len(samples) < 20:
                samples.append({k: row[k] for k in diagnostic})
            if len(candidates) < 20 and any(re.search(
                    r"vinyl|\blp\b", row[k], re.I) for k in diagnostic
                    if re.search(r"format|drager|subgroup", k, re.I)):
                safe = {"ean", "productId", "title", "Performer", "Author", "Format",
                        "AppearanceName", "BindingCode", "productPageUrlNL", "productPageUrlBE"}
                safe.update(k for k in headers if k.startswith(("OfferNL.", "OfferBE.")))
                candidates.append({k: row[k] for k in headers if k in safe})
            if read >= max_rows:
                break
        else:
            complete = True
    return {"status": "schema_inspected", "database_writes": 0, "errors": [],
            "headers": headers, "field_samples": samples, "vocabulary": vocabulary,
            "vinyl_candidate_samples": candidates, "read_products": read,
            "complete_feed": complete, "gzip_integrity": "verified_full_read" if complete else "not_fully_checked",
            "offers": [], "live_schema_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, help="Local CSV/XML(.gz); otherwise fetch FTPS")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--markets", default="NL")
    parser.add_argument("--limit", type=int, default=20, help="Selected products; 0=full bounded scan")
    parser.add_argument("--max-rows", type=int, default=1_000_000)
    parser.add_argument("--source-at", help="Local feed generation timestamp, ISO8601 with timezone")
    parser.add_argument("--output", type=Path, default=Path("output/bol/review.json"))
    parser.add_argument("--review-plan", type=Path, help="Trusted reviewed pilot selection; NL and <=20 products only")
    parser.add_argument("--explain-coverage", action="store_true")
    parser.add_argument("--diagnose-writer", action="store_true")
    parser.add_argument("--check-matches", action="store_true")
    parser.add_argument("--inspect-schema", action="store_true")
    parser.add_argument("--expected-feed-sha256", help="Bind an approved pilot to its reviewed source bytes")
    parser.add_argument("--state", type=Path, help="Successful full-writer checkpoint; skips unchanged remote MDTM")
    parser.add_argument("--validation-suite", action="store_true", help="20-product pilot and full read-only scan from one download")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--approve-publication", action="store_true")
    args = parser.parse_args(argv)
    started = time.monotonic()
    report = {"status": "blocked", "database_writes": 0, "errors": []}
    try:
        if args.diagnose_writer:
            if args.write:
                raise FeedError("writer_diagnostics_cannot_publish")
            report = writer_diagnostics(os.environ["DATABASE_URL"])
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report))
            return 0
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        if args.validation_suite and args.limit != 0:
            raise FeedError("validation_suite_requires_limit_zero")
        if args.state and (not args.write or args.limit != 0 or args.feed):
            raise FeedError("state_requires_full_remote_writer")
        if args.validation_suite and (args.write or args.inspect_schema):
            raise FeedError("validation_suite_is_read_only_and_not_schema_inspection")
        if args.write and (not args.approve_publication or not profile.get("live_schema_verified")):
            raise FeedError("approve_publication_and_verified_live_schema_required")
        if args.write and not set(args.markets.split(",")).issubset(profile.get("verified_markets", [])):
            raise FeedError("market_not_live_verified")
        if args.review_plan:
            if (not args.write or args.limit != 20 or args.markets != "NL" or args.feed or args.state):
                raise FeedError("reviewed_plan_requires_approved_bounded_nl_pilot")
            report = reviewed_pilot(args.review_plan, args.expected_feed_sha256, os.environ.get("BOL_SITE_ID", ""))
            shops = json.loads(os.environ.get("BOL_SHOP_IDS", "{}"))
            review_matches(report, os.environ["DATABASE_URL"], shops)
            if report.get("match_conflicts"):
                raise FeedError("reviewed_pilot_has_database_conflicts")
            result = publish(report, os.environ["DATABASE_URL"], shops, approved=True)
            report.update(write_result=result, database_writes=result["updated_offers"], status="written",
                          duration_seconds=round(time.monotonic() - started, 3))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(json.dumps({k:v for k,v in report.items() if k not in {"offers", "skip_samples"}}))
            return 0
        audit_gtins = None
        if args.explain_coverage:
            if not args.check_matches or args.inspect_schema or args.limit != 0:
                raise FeedError("coverage_explanation_requires_full_read_only_match_review")
            audit_gtins = load_coverage_gtins(os.environ["DATABASE_URL"],
                json.loads(os.environ.get("BOL_SHOP_IDS", "{}")))
        checkpoint_key = hashlib.sha256(json.dumps({
            "profile": profile, "markets": args.markets, "site_id": os.environ.get("BOL_SITE_ID"),
            "shops": os.environ.get("BOL_SHOP_IDS"), "database": os.environ.get("DATABASE_URL"),
        }, sort_keys=True).encode()).hexdigest()
        previous_source = None
        if args.state and args.state.exists():
            previous = json.loads(args.state.read_text(encoding="utf-8"))
            if previous.get("key") == checkpoint_key:
                previous_source = datetime.fromisoformat(previous["source_at"])
        with tempfile.TemporaryDirectory(prefix="bol-feed-") as directory:
            path = args.feed or Path(directory) / FEED_NAME
            source_at = datetime.fromisoformat(args.source_at) if args.source_at else None
            if not args.feed:
                source_at = download_feed(path, unchanged_since=previous_source)
                if previous_source is not None and source_at == previous_source and not path.exists():
                    report.update(status="unchanged_feed", source_at=source_at.isoformat(),
                                  database_writes=0, duration_seconds=round(time.monotonic() - started, 3))
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                    print(json.dumps(report))
                    return 0
            if args.write and source_at is None:
                raise FeedError("local_write_requires_proven_source_timestamp")
            integrity = verify_integrity(path)
            if args.inspect_schema:
                if args.write or args.check_matches:
                    raise FeedError("schema_inspection_cannot_write_or_query_database")
                report = inspect_schema(path, profile, max_rows=args.max_rows)
            else:
                report = build_plan(path, profile, args.markets.split(","), os.environ.get("BOL_SITE_ID", ""),
                                    limit=args.limit, max_rows=args.max_rows, captured_at=source_at, audit_gtins=audit_gtins)
            report["file_validation"] = integrity
            report["valid_prices"] = len(report.get("offers", []))
            report["source_at"] = source_at.isoformat() if source_at else None
            report["source_timestamp_status"] = "provided_or_ftp_mdtm" if source_at else "unknown_dry_run_only"
            report["feed_sha256"] = file_digest(path)
            if args.expected_feed_sha256 and report["feed_sha256"] != args.expected_feed_sha256:
                raise FeedError("reviewed_feed_checksum_mismatch")
            if not args.inspect_schema:
                report["status"] = "dry_run" if report["offers"] else "no_eligible_offers"
            if args.validation_suite:
                pilot = build_plan(path, profile, args.markets.split(","), os.environ.get("BOL_SITE_ID", ""),
                                   limit=20, max_rows=args.max_rows, captured_at=source_at)
                if args.check_matches:
                    review_matches(pilot, os.environ["DATABASE_URL"],
                                   json.loads(os.environ.get("BOL_SHOP_IDS", "{}")))
                report["pilot_20"] = {k: v for k, v in pilot.items() if k != "offers"}
                report["pilot_20"]["valid_prices"] = len(pilot["offers"])
            if args.check_matches or (args.write and profile.get("quarantine_identity_conflicts")):
                review_matches(report, os.environ["DATABASE_URL"],
                               json.loads(os.environ.get("BOL_SHOP_IDS", "{}")))
            if profile.get("quarantine_identity_conflicts") and report.get("match_status") == "read_only_checked":
                quarantine_identity_conflicts(report)
            if args.write:
                if args.limit == 0 and not report["complete_feed"]:
                    raise FeedError("full_import_row_ceiling_reached")
                shops = json.loads(os.environ.get("BOL_SHOP_IDS", "{}"))
                result = publish(report, os.environ["DATABASE_URL"], shops, approved=True)
                report["write_result"] = result
                report["database_writes"] = result["updated_offers"]
                report["status"] = "written"
                if args.state and report["complete_feed"]:
                    args.state.parent.mkdir(parents=True, exist_ok=True)
                    temporary_state = args.state.with_suffix(args.state.suffix + ".tmp")
                    temporary_state.write_text(json.dumps({"key": checkpoint_key, "source_at": source_at.isoformat()}), encoding="utf-8")
                    temporary_state.replace(args.state)
    except Exception as exc:
        # Never echo driver messages, secret paths/URLs or traceback.
        report["status"] = "blocked"
        report["errors"] = [str(exc) if isinstance(exc, FeedError) else type(exc).__name__]
        if args.write:
            # Commit can be ambiguous on connection loss; never assert zero.
            report["database_writes"] = None
    report["duration_seconds"] = round(time.monotonic() - started, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"offers", "skip_samples", "field_samples", "vinyl_candidate_samples", "vocabulary", "coverage_source_rejections", "coverage_source_absent_gtins"}}))
    return 1 if report["errors"] or (not report.get("offers") and report["status"] != "schema_inspected") else 0


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
