"""Conservative RareVinyl USF staging preview. This module never writes to a DB."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4
from scripts.importers.common import strict_normalize_gtin
from scripts.scrapers.usf.core.staging import build_stage_item
from psycopg.types.json import Jsonb


def preview_record(row):
    parsed = urlsplit(row.get('url') or '')
    if parsed.scheme != 'https' or parsed.hostname != 'eu.rarevinyl.com' or not parsed.path.startswith('/products/') or parsed.query or parsed.fragment:
        raise ValueError('invalid_source_url')
    if row.get('format_status') != 'vinyl' or row.get('condition_status') != 'new':
        return {'route': 'quarantine', 'reason': 'new_vinyl_not_confirmed'}
    if not row.get('artist') or not row.get('album_raw'):
        return {'route': 'review', 'reason': 'missing_artist_or_title'}
    barcode = row.get('barcode')
    gtin = strict_normalize_gtin(barcode) if barcode else None
    if barcode and not gtin:
        return {'route': 'quarantine', 'reason': 'invalid_barcode'}
    raw = {'id': str(uuid4()), 'shop_id': 'rarevinyl', 'source_url': row['url'],
           'source_product_id': row['source_id'], 'title_raw': row['title_raw'],
           'ean_raw': barcode, 'price_raw': row['price'],
           'availability_raw': row.get('availability'),
           'scraped_at': datetime.now(timezone.utc),
           'payload': {'artist_raw': row['artist'], 'album_raw': row['album_raw'],
                       'format_status': row['format_status'], 'condition_status': row['condition_status'],
                       'listing_observed_at': row.get('observed_at')}}
    staged = build_stage_item(raw)
    if staged.price is None or staged.price <= 0:
        return {'route': 'quarantine', 'reason': 'invalid_price', 'raw': raw}
    if not barcode:
        return {'route': 'artist_title', 'reason': 'missing_ean', 'raw': raw}
    if staged.stage_reason:
        return {'route': 'quarantine', 'reason': staged.stage_reason, 'raw': raw}
    return {'route': 'ean_staging', 'gtin14': gtin, 'raw': raw}


def write_raw(conn, rows):
    """Persist one bounded source batch atomically; never publish prices/products.

    Existing observations are reused by source identity and full payload hash.
    The caller must provide fresh, verified source observations. This function
    is intentionally not connected to any scheduled workflow yet.
    """
    import hashlib
    import json
    if len(rows) > 100:
        raise ValueError('maximum batch size is 100')
    urls = [row.get('url') for row in rows]
    if len(set(urls)) != len(urls):
        raise ValueError('duplicate source URLs')
    prepared = [preview_record(row) for row in rows]
    if any(result['route'] == 'quarantine' for result in prepared):
        raise ValueError('batch contains quarantined records')
    inserted = reused = 0
    with conn.transaction():
        conn.execute("set local lock_timeout='3s';set local statement_timeout='30s'")
        conn.execute("select pg_advisory_xact_lock(hashtextextended('rarevinyl_source_raw_v1',0))")
        for row, result in zip(rows, prepared):
            if result['route'] not in ('ean_staging', 'artist_title'):
                continue
            raw = result['raw']
            source = {k: v for k, v in row.items() if k not in ('observed_at', 'detail_checked_at')}
            digest = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            previous = conn.execute("""select payload->>'source_hash' from raw_shop_scrapes
              where shop_id='rarevinyl' and source_url=%s order by scraped_at desc limit 1""", (raw['source_url'],)).fetchone()
            if previous and previous[0] == digest:
                reused += 1
                continue
            observed = datetime.fromisoformat(row['observed_at'])
            if observed.tzinfo is None or not 0 <= (datetime.now(timezone.utc)-observed).total_seconds() <= 3600:
                raise ValueError('source_observation_not_fresh')
            payload = dict(raw['payload']) | {'source_hash': digest, 'source_record': source,
                                             'currency': 'EUR', 'availability': raw['availability_raw']}
            conn.execute("""insert into raw_shop_scrapes(id,shop_id,source_url,source_product_id,title_raw,ean_raw,
              price_raw,availability_raw,payload,scraped_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (raw['id'], raw['shop_id'], raw['source_url'], raw['source_product_id'], raw['title_raw'],
               raw['ean_raw'], raw['price_raw'], raw['availability_raw'], Jsonb(payload), observed))
            inserted += 1
    return {'inserted': inserted, 'reused': reused, 'prices_written': 0, 'products_written': 0}
