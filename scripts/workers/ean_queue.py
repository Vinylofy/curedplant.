"""New-only EAN selection and metadata writes using existing USF tables."""
from __future__ import annotations

from datetime import datetime, timezone
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from scripts.importers.common import CanonicalRecord, infer_artist_title, upsert_product
from scripts.scrapers.usf.core.db import db_connection


class EanQueue:
    def fresh_catalog_rows(self, shop, rows):
        if not rows:
            return []
        urls = [row["source_url"] for row in rows]
        with db_connection() as conn, conn.cursor() as cur:
            cur.execute("""
                select source_url from public.shop_product_links
                where shop_id=%s and source_url=any(%s)
                  and (last_detail_scraped_at is not null or ean_next_attempt_at>now()
                       or ean_enrichment_status='found')
                union select source_url from public.raw_shop_scrapes
                where shop_id=%s and source_url=any(%s) and nullif(ean_raw,'') is not null
            """, (shop, urls, shop, urls))
            done = {row[0] for row in cur.fetchall()}
        return [row for row in rows if row["source_url"] not in done]

    def candidates(self, shop, limit):
        with db_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                select l.id, l.source_url, l.source_product_id, l.payload
                from public.shop_product_links l
                where l.shop_id = %s and l.status = 'active'
                  and l.last_detail_scraped_at is null
                  and coalesce(l.ean_enrichment_status,'pending') <> 'found'
                  and (l.ean_next_attempt_at is null or l.ean_next_attempt_at <= now())
                  and not exists (
                    select 1 from public.raw_shop_scrapes r
                    where r.shop_id = l.shop_id and r.source_url = l.source_url
                      and nullif(r.ean_raw, '') is not null)
                order by l.first_seen_at asc, l.id asc limit %s
            """, (shop, limit))
            return [dict(row) for row in cur.fetchall()]

    def register(self, shop, rows):
        # Merge payloads so existing enrichment/counters survive rediscovery.
        # last_detail_scraped_at and next-attempt fields are never reset here.
        with db_connection() as conn, conn.cursor() as cur:
            for row in rows:
                cur.execute("""
                    insert into public.shop_product_links
                        (shop_id, source_url, source_product_id, first_seen_at, last_seen_at, status, payload)
                    values (%s,%s,%s,now(),now(),'active',%s)
                    on conflict (shop_id, source_url) do update set
                        last_seen_at=now(), status='active',
                        source_product_id=coalesce(excluded.source_product_id,shop_product_links.source_product_id),
                        payload=coalesce(shop_product_links.payload,'{}'::jsonb) || excluded.payload
                """, (shop, row["source_url"], row.get("source_product_id"), Jsonb(row["payload"])))

    def claim(self, shop, row):
        # Same two-hour lease fields already used by the native Bob worker.
        with db_connection() as conn, conn.cursor() as cur:
            cur.execute("""
                update public.shop_product_links l
                set ean_next_attempt_at=now()+interval '2 hours', ean_last_result='processing'
                where l.id=%s and l.shop_id=%s and l.status='active'
                  and l.last_detail_scraped_at is null
                  and coalesce(l.ean_enrichment_status,'pending') <> 'found'
                  and (l.ean_next_attempt_at is null or l.ean_next_attempt_at<=now())
                  and not exists (select 1 from public.raw_shop_scrapes r
                    where r.shop_id=l.shop_id and r.source_url=l.source_url
                      and nullif(r.ean_raw,'') is not null)
                returning l.id
            """, (row["id"], shop))
            return cur.fetchone() is not None

    def finish(self, shop, row, result):
        ean = result.get("ean")
        outcome = "technical_error" if result.get("error") else "found" if ean else "not_found"
        payload = {"curedplant_daily_ean": result}
        if ean:
            payload.update(last_successful_ean=ean, last_successful_ean_at=datetime.now(timezone.utc).isoformat())
        with db_connection() as conn, conn.cursor() as cur:
            cur.execute("""
                insert into public.raw_shop_scrapes
                    (run_id, shop_id, source_url, source_product_id, title_raw, ean_raw,
                     price_raw, availability_raw, image_url_raw, payload)
                values (null,%s,%s,%s,%s,%s,null,null,%s,%s)
            """, (shop, row["source_url"], row.get("source_product_id"), result.get("title"),
                  ean, result.get("image_url"), Jsonb({"source":"curedplant_daily_ean", **result})))
            cur.execute("""
                update public.shop_product_links
                set last_detail_scraped_at=now(), ean_enrichment_status=%s,
                    ean_last_result=%s, ean_next_attempt_at=null,
                    payload=coalesce(payload,'{}'::jsonb) || %s
                where id=%s and shop_id=%s
            """, (outcome, outcome, Jsonb(payload), row["id"], shop))
            # EAN updates may create/enrich product identity, never an offer,
            # price, availability or price-history row. Price is an unused
            # CanonicalRecord field in this metadata-only call.
            if ean and result.get("title"):
                data = row.get("payload") or {}
                artist, title = infer_artist_title(data.get("artist_raw") or data.get("artist"), result["title"])
                record = CanonicalRecord(source_row_number=0, shop_name=shop,
                    shop_domain=result["domain"], shop_country="NL", ean=ean, artist=artist, title=title,
                    format_label=data.get("format") or data.get("carrier"), cover_url=result.get("image_url"),
                    product_url=row["source_url"], price=0.0, currency=data.get("currency") or "EUR",
                    availability="unknown", captured_at=datetime.now(timezone.utc), product_handle=None,
                    detail_status="ok", is_secondhand=result.get("is_secondhand", False), raw=result,
                    gtin_normalized=ean)
                upsert_product(cur, record)
