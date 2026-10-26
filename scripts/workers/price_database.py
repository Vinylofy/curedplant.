"""Price-only updates of existing offers, with exact post-write verification."""
from __future__ import annotations

from decimal import Decimal
import os
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from scripts.workers.price_evidence import url_key
from scripts.scrapers.usf.core.listing_price_sync import normalize_availability


def shop_domain(worker, rows):
    domains = {r.get("shop_domain") for r in rows if r.get("shop_domain")}
    if len(domains) == 1:
        return domains.pop()
    overrides = {"cdhal": "cdhal.nl", "fiftiesstore": "fiftiesstore.nl", "imusic": "imusic.nl",
                 "jpc": "jpc.de", "musiconvinyl": "musiconvinyl.com", "dgmoutlet": "dgmoutlet.nl"}
    if worker in overrides:
        return overrides[worker]
    from scripts.importers.registry import get_shop_importer
    return get_shop_importer(worker).config.shop_domain


def update_existing(worker, records, started_at, *, allow_no_matches=False):
    """Never creates products/offers or changes EAN, covers or detail queues."""
    domain = shop_domain(worker, records)
    expected = {url_key(r["source_url"]): r for r in records}
    stats = {"shop_domain": domain, "matched": 0, "updated": 0, "changed": 0,
             "skipped_newer": 0, "unmatched": 0, "verified": 0, "samples": [],
             "quarantined_urls": []}
    written = []
    with psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("select id from public.shops where domain=%s", (domain,))
            shops = cur.fetchall()
            if len(shops) != 1:
                raise RuntimeError(f"Expected one registered shop for {domain}; found {len(shops)}")
            shop_id = shops[0]["id"]
            # One narrowly scoped shop snapshot. Stable lock order prevents
            # two price writers taking these rows in opposite orders.
            cur.execute("""select product_id,product_url from public.prices where shop_id=%s""", (shop_id,))
            registered = cur.fetchall()
            fallbacks = {}
            if worker == "variaworld" and any(row.get("identity_proof") for row in records):
                from scripts.workers.variaworld_identity import fallback_matches
                cur.execute("""select pr.product_id,pr.product_url,p.ean,p.gtin_normalized
                    from public.prices pr join public.products p on p.id=pr.product_id
                    where pr.shop_id=%s""", (shop_id,))
                fallbacks = fallback_matches(records, cur.fetchall())
            target_ids = [r["product_id"] for r in registered
                          if url_key(r["product_url"]) in expected or str(r["product_id"]) in fallbacks]
            cur.execute("""select product_id, shop_id, product_url, price, currency,
                                  availability, last_seen_at, is_active
                           from public.prices where shop_id=%s
                             and product_id=any(%s)
                           order by product_id for update""", (shop_id, target_ids))
            targets = cur.fetchall()
            target_records = {str(t["product_id"]): expected.get(url_key(t["product_url"]))
                              or fallbacks.get(str(t["product_id"])) for t in targets}
            matched_keys = set()
            keys = [url_key(t["product_url"]) for t in targets]
            from collections import Counter
            counts = Counter(keys)
            ambiguous = {key for key, count in counts.items() if count > 1}
            stats["quarantined_urls"] = sorted({target_records[str(t["product_id"])]["source_url"]
                                         for t in targets if url_key(t["product_url"]) in ambiguous})
            # No arbitrary product choice: ambiguous URLs get no write. A
            # widespread identity problem still stops the entire shop.
            if ambiguous and len(ambiguous) / len(counts) > .1:
                raise RuntimeError(f"More than 10% of matched URLs need variant review: {stats['quarantined_urls'][:12]}")
            targets = [target for target in targets if url_key(target["product_url"]) not in ambiguous]
            changes = []
            for target in targets:
                key = url_key(target["product_url"])
                record = target_records.get(str(target["product_id"]))
                if record is None:
                    continue
                matched_keys.add(url_key(record["source_url"]))
                stats["matched"] += 1
                if target["last_seen_at"] and target["last_seen_at"] > started_at:
                    stats["skipped_newer"] += 1
                    continue
                if record["currency"] != target["currency"]:
                    raise RuntimeError(f"Currency mismatch for {record['source_url']}")
                value = Decimal(record["price"])
                availability = normalize_availability(record.get("availability"))
                if availability == "unknown":
                    availability = target["availability"]
                changed = value != target["price"] or availability != target["availability"]
                product_url = (record["source_url"] if str(target["product_id"]) in fallbacks
                               else target["product_url"])
                changes.append({"product_id": str(target["product_id"]), "product_url": product_url, "price": str(value),
                                "currency": record["currency"], "availability": availability,
                                "changed": changed})
                stats["updated"] += 1
                stats["changed"] += int(changed)
                written.append((target["product_id"], value, availability, product_url))
                if len(stats["samples"]) < 12:
                    stats["samples"].append({"url": record["source_url"], "before": str(target["price"]), "after": str(value), "currency": record["currency"]})
            stats["unmatched"] = len(expected) - len(matched_keys)
            if not written and allow_no_matches and stats["matched"] == stats["skipped_newer"]:
                return stats
            if not written:
                raise RuntimeError(f"No existing prices updated: matched={stats['matched']}, newer={stats['skipped_newer']}")
            for offset in range(0, len(changes), 2000):
                batch = Jsonb(changes[offset:offset + 2000])
                cur.execute("""update public.prices p
                    set price=v.price,availability=v.availability,product_url=v.product_url,last_seen_at=%s,
                        updated_at=now(),is_active=true
                    from jsonb_to_recordset(%s::jsonb)
                         as v(product_id uuid,price numeric,availability text,product_url text)
                    where p.product_id=v.product_id and p.shop_id=%s""", (started_at, batch, shop_id))
                if cur.rowcount != len(changes[offset:offset + 2000]):
                    raise RuntimeError("Existing offer target count changed; rolling back")
                cur.execute("""insert into public.price_history
                    (product_id,shop_id,price,currency,availability,captured_at,created_at)
                    select v.product_id,%s,v.price,v.currency,v.availability,%s,now()
                    from jsonb_to_recordset(%s::jsonb) as v
                      (product_id uuid,price numeric,currency text,availability text,changed boolean)
                    where v.changed""", (shop_id, started_at, batch))
            # Verify before commit; a mismatch rolls back the entire write.
            cur.execute("""select product_id,price,availability,product_url,last_seen_at from public.prices
                           where shop_id=%s and product_id=any(%s)""", (shop_id, [r[0] for r in written]))
            actual = {str(r["product_id"]): (r["price"], r["availability"], r["product_url"], r["last_seen_at"]) for r in cur.fetchall()}
            for product_id, value, availability, product_url in written:
                if actual.get(str(product_id)) != (value, availability, product_url, started_at):
                    raise RuntimeError("Price postcondition failed; rolling back")
        conn.commit()
    # Independent connection proves committed values, not only transaction state.
    with psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""select product_id,price,availability,product_url,last_seen_at from public.prices
                       where shop_id=%s and product_id=any(%s)""", (shop_id, [r[0] for r in written]))
        actual = {str(r["product_id"]): (r["price"], r["availability"], r["product_url"], r["last_seen_at"]) for r in cur.fetchall()}
        for product_id, value, availability, product_url in written:
            if actual.get(str(product_id)) != (value, availability, product_url, started_at):
                raise RuntimeError("Committed price verification failed; schedule must stay off")
            stats["verified"] += 1
    return stats
