"""Build validated listing-price input for the existing price-only writer.

The writer is intentionally not invoked here. Source conditions must have
been independently verified and the caller must establish source freshness.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from scripts.workers.price_evidence import url_key


def price_records(rows, now=None):
    now = now or datetime.now(timezone.utc)
    records = {}
    rejected = []
    for row in rows:
        url = row.get('url') or ''
        parsed = urlsplit(url)
        try:
            if parsed.scheme != 'https' or parsed.hostname != 'eu.rarevinyl.com' or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.query or parsed.fragment or not parsed.path.startswith('/products/'):
                raise ValueError('invalid_url')
            if row.get('condition_status') != 'new' or row.get('format_status') != 'vinyl':
                raise ValueError('new_vinyl_not_confirmed')
            checked = datetime.fromisoformat(row.get('detail_checked_at') or '')
            if checked.tzinfo is None or not 0 <= (now-checked).total_seconds() <= 30*86400:
                raise ValueError('condition_evidence_stale')
            if not str(row.get('condition_evidence') or '').lower().startswith('factory sealed from new. this item is unplayed.'):
                raise ValueError('condition_evidence_missing')
            if row.get('currency') != 'EUR':
                raise ValueError('invalid_currency')
            value = Decimal(str(row.get('price')))
            if not value.is_finite() or value <= 0 or value.as_tuple().exponent < -2:
                raise ValueError('invalid_price')
            observed = datetime.fromisoformat(row.get('observed_at') or '')
            if observed.tzinfo is None or not 0 <= (now-observed).total_seconds() <= 3600:
                raise ValueError('stale_listing')
            if row.get('availability') not in ('in_stock','out_of_stock','preorder','unknown'):
                raise ValueError('invalid_availability')
            item = {'source_url':url, 'shop_domain':'eu.rarevinyl.com', 'price':str(value),
                    'currency':'EUR', 'availability':row['availability'], 'observed_at':observed.isoformat()}
            key = url_key(url)
            if key in records:
                raise ValueError('duplicate_url')
            records[key] = item
        except (ValueError, TypeError, InvalidOperation) as error:
            rejected.append({'url':url, 'reason':str(error)})
    if any(r['reason']=='duplicate_url' for r in rejected):
        raise ValueError('ambiguous_duplicate_listing')
    return {'records':list(records.values()), 'rejected':rejected, 'database_writes':0}


def sync_existing(rows, *, write=False, writer=None, now=None):
    """Update only registered shop URLs; no creation of products or offers."""
    if len(rows) > 100:
        raise ValueError('maximum batch size is 100')
    assessed = price_records(rows, now=now)
    if not write or not assessed['records']:
        return assessed | {'mode':'dry_run' if not write else 'no_eligible_records'}
    if writer is None:
        from scripts.workers.price_database import update_existing
        writer = update_existing
    # Using the oldest observation avoids overwriting any write that occurred
    # after a listing was collected, even when the batch spans multiple pages.
    started_at = min(datetime.fromisoformat(r['observed_at']) for r in assessed['records'])
    result = writer('rarevinyl', assessed['records'], started_at,
                    allow_no_matches=True, preserve_unknown=True)
    return {'mode':'write', 'eligible':len(assessed['records']),
            'rejected':assessed['rejected'], 'database_writes':result['updated'], 'writer':result}


def main():
    import argparse
    import json
    import os
    from pathlib import Path
    import psycopg
    from scripts.workers.rarevinyl_staging import verify_project
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    capture = json.loads(args.capture.read_text())
    if capture.get('status')!='research_only' or capture.get('database_writes')!=0 or capture.get('publication_blocked') is not True:
        raise ValueError('invalid_source_capture')
    rows = capture.get('records')
    if not isinstance(rows,list) or capture.get('errors'):
        raise ValueError('incomplete_source_capture')
    if args.write:
        with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,connect_timeout=20) as conn:
            verify_project(conn,os.environ.get('SUPABASE_URL',''))
    print(json.dumps(sync_existing(rows,write=args.write),default=str))

if __name__ == '__main__':
    main()
