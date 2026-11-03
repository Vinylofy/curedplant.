"""Conservative RareVinyl USF staging preview. This module never writes to a DB."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4
from scripts.importers.common import strict_normalize_gtin
from scripts.scrapers.usf.core.staging import build_stage_item
from psycopg.types.json import Jsonb


def preview_record(row):
    parsed = urlsplit(row.get('url') or '')
    if parsed.scheme != 'https' or parsed.hostname != 'eu.rarevinyl.com' or parsed.username or parsed.password or parsed.port not in (None,443) or not parsed.path.startswith('/products/') or parsed.query or parsed.fragment:
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


def checkpoint_page(conn, page, rows, end_of_catalogue=False):
    """Atomically retain listing evidence and the next page in the source registry.

    Only a complete listing response may be checkpointed. URLs and IDs are
    validated before any mutation. This function never publishes offers.
    """
    import hashlib
    if not isinstance(page, int) or page < 1 or len(rows) > 50:
        raise ValueError('invalid_page_or_batch')
    if not rows and not end_of_catalogue:
        raise ValueError('empty_page_without_end_confirmation')
    urls = [row.get('url') for row in rows]
    ids = [row.get('source_id') for row in rows]
    if len(set(urls)) != len(urls) or len(set(ids)) != len(ids) or any(not str(i or '').isdigit() for i in ids):
        raise ValueError('duplicate_or_invalid_source_identity')
    for row in rows:
        parsed = urlsplit(row.get('url') or '')
        if parsed.scheme != 'https' or parsed.hostname != 'eu.rarevinyl.com' or parsed.username or parsed.password or parsed.port not in (None,443) or not parsed.path.startswith('/products/') or parsed.query or parsed.fragment:
            raise ValueError('invalid_source_url')
        at = datetime.fromisoformat(row['observed_at'])
        if at.tzinfo is None or not 0 <= (datetime.now(timezone.utc)-at).total_seconds() <= 3600:
            raise ValueError('source_observation_not_fresh')
    with conn.transaction():
        conn.execute("set local lock_timeout='3s';set local statement_timeout='30s'")
        conn.execute("select pg_advisory_xact_lock(hashtextextended('rarevinyl_source_checkpoint_v1',0))")
        current = conn.execute("select next_page, cycle_complete, last_page_signature from rarevinyl_source_checkpoint where name='discovery' for update").fetchone()
        expected = current[0] if current else 1
        if current and current[1]:
            raise ValueError('cycle_complete_requires_explicit_restart')
        if page != expected:
            raise ValueError('checkpoint_page_mismatch')
        signature = hashlib.sha256(','.join(sorted(str(i) for i in ids)).encode()).hexdigest() if rows else None
        if signature and current and signature == current[2]:
            raise ValueError('repeated_listing_page')
        for row in rows:
            existing = conn.execute("""select source_url from shop_product_links
              where shop_id='rarevinyl' and source_product_id=%s and source_url<>%s limit 1""",
              (row['source_id'], row['url'])).fetchone()
            if existing:
                raise ValueError('source_id_conflicts_with_existing_url')
            written = conn.execute("""insert into shop_product_links(shop_id,source_url,source_product_id,status,payload)
              values('rarevinyl',%s,%s,'active',%s) on conflict(shop_id,source_url) do update set
              source_product_id=excluded.source_product_id,last_seen_at=now(),
              payload=shop_product_links.payload || excluded.payload
              where shop_product_links.source_product_id=excluded.source_product_id returning id""",
              (row['url'], row['source_id'], Jsonb({'listing':row}))).fetchone()
            if not written:
                raise ValueError('source_id_conflicts_with_existing_url')
        conn.execute("""insert into rarevinyl_source_checkpoint(name,next_page,cycle_complete,last_page_signature)
          values('discovery',%s,%s,%s) on conflict(name) do update set next_page=excluded.next_page,
          cycle_complete=excluded.cycle_complete,last_page_signature=excluded.last_page_signature,updated_at=now()""", (page if end_of_catalogue else page+1,end_of_catalogue,signature))
    return {'next_page':page if end_of_catalogue else page+1, 'retained':len(rows), 'cycle_complete':end_of_catalogue}


def ingest_capture(conn, capture):
    """Persist a single complete capture; a retry reuses raw observations.

    Non-eligible records remain in the listing registry for later enrichment.
    No price or product publication takes place here.
    """
    if capture.get('status') != 'research_only' or capture.get('database_writes') != 0 or capture.get('publication_blocked') is not True:
        raise ValueError('invalid_capture_envelope')
    page = capture.get('start_page')
    rows = capture.get('records')
    errors = capture.get('errors')
    if not isinstance(page, int) or not isinstance(rows, list) or not isinstance(errors, list) or errors:
        raise ValueError('incomplete_or_invalid_capture')
    if len(rows) > 50 or capture.get('summary', {}).get('discovered') != len(rows):
        raise ValueError('capture_page_size_or_count_mismatch')
    eligible = [row for row in rows if preview_record(row)['route'] in ('ean_staging', 'artist_title')]
    with conn.transaction():
        # Both nested operations are savepoints inside this transaction. A
        # failed checkpoint must also roll back any inserted raw observations.
        raw = write_raw(conn, eligible)
        checkpoint = checkpoint_page(conn, page, rows, capture.get('end_of_catalogue') is True)
    return {'raw':raw, 'checkpoint':checkpoint, 'pending_detail':len(rows)-len(eligible)}
