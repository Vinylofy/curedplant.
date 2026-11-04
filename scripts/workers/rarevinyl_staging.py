"""Conservative RareVinyl source staging; database writes require explicit opt-in."""
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
    if not str(row.get('condition_evidence') or '').lower().startswith('factory sealed from new. this item is unplayed.'):
        return {'route': 'quarantine', 'reason': 'condition_evidence_missing'}
    if not row.get('artist') or not row.get('album_raw'):
        return {'route': 'review', 'reason': 'missing_artist_or_title'}
    barcode = row.get('barcode')
    if row.get('barcode_status') == 'invalid' or (row.get('barcode_raw') and not strict_normalize_gtin(row['barcode_raw'])):
        return {'route': 'quarantine', 'reason': 'invalid_barcode'}
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
                       'format': 'Vinyl',
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
    if capture.get('status') != 'research_only' or capture.get('database_writes') != 0 or capture.get('publication_blocked') is not True or capture.get('verified_markets') != ['NL','BE']:
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


def pending_details(conn, limit=10):
    """Return bounded listing snapshots awaiting source-detail verification."""
    if not 1 <= limit <= 50:
        raise ValueError('detail limit must be between 1 and 50')
    rows = conn.execute("""select source_url,source_product_id,payload->'listing'
        from shop_product_links where shop_id='rarevinyl' and status='active'
          and (last_detail_scraped_at is null or last_detail_scraped_at < now() - interval '30 days')
          and last_seen_at >= now() - interval '1 hour'
          and payload->'listing'->>'format_status'='vinyl'
          and payload->'listing'->>'sealed_candidate'='true'
        order by first_seen_at,id limit %s""", (limit,)).fetchall()
    return [dict(row[2] or {}, url=row[0], source_id=row[1]) for row in rows]


def persist_detail(conn, row):
    """Write validated source evidence and mark exactly its registry item done."""
    result = preview_record(row)
    if result['route'] not in ('ean_staging','artist_title'):
        raise ValueError('detail_requires_review')
    checked = datetime.fromisoformat(row.get('detail_checked_at') or '')
    if checked.tzinfo is None or not 0 <= (datetime.now(timezone.utc)-checked).total_seconds() <= 3600:
        raise ValueError('detail_observation_not_fresh')
    if not str(row.get('condition_evidence') or '').lower().startswith('factory sealed from new. this item is unplayed.'):
        raise ValueError('condition_evidence_missing')
    with conn.transaction():
        conn.execute("set local lock_timeout='3s';set local statement_timeout='30s'")
        link = conn.execute("""select id,payload->'listing' from shop_product_links
          where shop_id='rarevinyl' and source_url=%s and source_product_id=%s for update""",
          (row['url'],row['source_id'])).fetchone()
        if not link or not link[1]:
            raise ValueError('listing_registry_missing')
        # Listing price can change after fetching details. Never attach a
        # barcode or older condition proof to a different price/variant.
        for field in ('variant_id','price','observed_at'):
            if str(link[1].get(field)) != str(row.get(field)):
                raise ValueError('listing_changed_since_detail_fetch')
        raw = write_raw(conn,[row])
        conn.execute("""update shop_product_links set last_detail_scraped_at=%s,
          payload=payload || %s where id=%s""",
          (checked, Jsonb({'detail':row}), link[0]))
    return {'route':result['route'], 'raw':raw}


def verify_project(conn, supabase_url):
    """Refuse production writes unless the configured project matches the DB."""
    import re
    if not supabase_url:
        from pathlib import Path
        supabase_url = (Path(__file__).resolve().parents[2]/'config/rarevinyl-supabase-public-url.txt').read_text().strip()
    expected = re.fullmatch(r'([a-z0-9]{20})\.supabase\.co', urlsplit(supabase_url).hostname or '')
    host = conn.info.host or ''
    direct = re.fullmatch(r'db\.([a-z0-9]{20})\.supabase\.co', host)
    pooler = re.fullmatch(r'[a-z0-9.-]+\.pooler\.supabase\.com', host)
    login = re.fullmatch(r'postgres\.([a-z0-9]{20})', conn.info.user or '')
    actual = direct.group(1) if direct else (login.group(1) if pooler and login else None)
    if not expected or expected.group(1) != actual or str(conn.info.port) != '5432':
        raise ValueError('supabase_project_identity_not_verified')


def register_shop(conn):
    """Register the UK source shop without changing any product or offer."""
    with conn.transaction():
        conn.execute("set local lock_timeout='3s';set local statement_timeout='30s'")
        conn.execute("select pg_advisory_xact_lock(hashtextextended('rarevinyl_shop_registration_v1',0))")
        rows = conn.execute("select id,country,is_active from shops where lower(domain)='eu.rarevinyl.com' for update").fetchall()
        if len(rows) > 1:
            raise ValueError('ambiguous_registered_shop')
        if rows:
            if rows[0][1] != 'GB' or rows[0][2] is not True:
                raise ValueError('existing_shop_requires_review')
            shop_id = rows[0][0]
            created = False
        else:
            shop_id = conn.execute("insert into shops(name,domain,country,is_active) values('RareVinyl','eu.rarevinyl.com','GB',true) returning id").fetchone()[0]
            created = True
        return {'shop_id':str(shop_id), 'created':created, 'products_written':0, 'prices_written':0}


def restart_completed_cycle(conn):
    """Start a new listing pass only after the preceding pass reached EOF."""
    with conn.transaction():
        conn.execute("set local lock_timeout='3s'")
        conn.execute("select pg_advisory_xact_lock(hashtextextended('rarevinyl_source_checkpoint_v1',0))")
        row = conn.execute("select cycle_complete from rarevinyl_source_checkpoint where name='discovery' for update").fetchone()
        if not row or not row[0]:
            raise ValueError('previous_cycle_not_complete')
        conn.execute("update rarevinyl_source_checkpoint set next_page=1,cycle_complete=false,last_page_signature=null,updated_at=now() where name='discovery'")
    return {'next_page':1,'cycle_restarted':True}


def main():
    import argparse
    import json
    import os
    from pathlib import Path
    import psycopg
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--checkpoint', action='store_true')
    parser.add_argument('--install-checkpoint', action='store_true')
    parser.add_argument('--register-shop', action='store_true')
    parser.add_argument('--restart-completed', action='store_true')
    parser.add_argument('--stage-raw', action='store_true')
    parser.add_argument('--pending-details', type=int)
    parser.add_argument('--detail-capture', type=Path)
    args = parser.parse_args()
    if (args.install_checkpoint or args.register_shop or args.restart_completed or args.stage_raw) and not args.write:
        parser.error('installation or registration requires --write')
    if args.write and not (args.install_checkpoint or args.register_shop or args.restart_completed or args.stage_raw or args.capture or args.detail_capture):
        parser.error('a capture is required for writes')
    if not args.write and not args.checkpoint and not args.capture and args.pending_details is None:
        parser.error('select a capture or checkpoint query')
    if args.capture and not args.write and not args.checkpoint:
        capture = json.loads(args.capture.read_text())
        results = [preview_record(row) for row in capture['records']]
        print(json.dumps({'database_writes':0, 'routes':{route:sum(r['route']==route for r in results)
              for route in ('ean_staging','artist_title','review','quarantine')}}))
        return
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=True, connect_timeout=20) as conn:
        verify_project(conn, os.environ.get('SUPABASE_URL',''))
        if args.install_checkpoint:
            sql = (Path(__file__).resolve().parents[1]/'scrapers/usf/migrations/20261103_rarevinyl_source_checkpoint.sql').read_text()
            conn.execute(sql, prepare=False)
            print(json.dumps({'checkpoint_installed':True}))
        elif args.register_shop:
            print(json.dumps(register_shop(conn)))
        elif args.restart_completed:
            print(json.dumps(restart_completed_cycle(conn)))
        elif args.stage_raw:
            from scripts.scrapers.usf.core.staging import stage_latest_raw_snapshots
            result = stage_latest_raw_snapshots(shop_id='rarevinyl',limit=100,write=True)
            print(json.dumps({'candidates':result.candidates,'staged':result.inserted,'skipped':result.skipped}))
        elif args.checkpoint:
            row = conn.execute("select next_page,cycle_complete from rarevinyl_source_checkpoint where name='discovery'").fetchone()
            print(json.dumps({'next_page':row[0] if row else 1,'cycle_complete':row[1] if row else False}))
        elif args.pending_details is not None:
            print(json.dumps(pending_details(conn,args.pending_details),ensure_ascii=False,default=str))
        elif args.detail_capture:
            if not args.write: parser.error('detail-capture requires --write')
            capture = json.loads(args.detail_capture.read_text())
            if capture.get('status')!='research_only' or capture.get('database_writes')!=0 or capture.get('publication_blocked') is not True:
                raise ValueError('invalid_detail_capture')
            rows = capture.get('records')
            if not isinstance(rows,list) or len(rows)>50: raise ValueError('invalid_detail_batch')
            results, rejected = [], []
            for row in rows:
                try:
                    results.append(persist_detail(conn,row))
                except ValueError as error:
                    if str(error) not in ('detail_requires_review','listing_changed_since_detail_fetch'):
                        raise
                    rejected.append({'source_id':row.get('source_id'), 'reason':str(error)})
            print(json.dumps({'processed':len(results),'raw_inserted':sum(r['raw']['inserted'] for r in results),
                              'source_errors':len(capture.get('errors',[])), 'review':rejected},default=str))
        elif args.write:
            print(json.dumps(ingest_capture(conn, json.loads(args.capture.read_text())), default=str))

if __name__ == '__main__':
    main()
