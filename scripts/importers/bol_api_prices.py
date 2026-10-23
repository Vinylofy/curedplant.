"""Bounded, resumable NL price refresh for existing, barcode-verified vinyl."""
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

from scripts.importers.bol_api_review import authenticate, request_json, ReviewError, CATALOG_URL, EANS
from scripts.importers.bol_feed import FeedError, amount, affiliate_link, product_link, publish
from scripts.importers.common import strict_normalize_gtin

SHOP_ID = 'f08437c2-1d85-47a6-94f9-33a55612d5cc'
VINYL_FORMATS = ('vinyl', 'lp', '7 inch', '10 inch', '12 inch', '7"', '10"', '12"',
                 '7" vinyl', '10" vinyl', '12" vinyl') + tuple(
    label for count in range(1, 21) for label in (f'{count}lp', f'{count}xlp', f'lp ({count})'))
VINYL_SQL = "(lower(trim(format_label))=any(%s) or lower(trim(format_label)) like 'vinyl |%%')"


def is_vinyl_format(value):
    text = str(value or '').strip().lower()
    if text in VINYL_FORMATS:
        return True
    if re.search(r'\b(cd|dvd|blu-ray|cassette|digital|download)\b', text):
        return False
    return text.startswith('vinyl |') and bool(re.search(r'\b(lp|(7|10|12)\s*inch)\b', text))

STATE_PATH = Path('state/bol-api/nl.json')


class Client:
    def __init__(self):
        self.token = None
        self.expires_at = 0
        self.last_request = None
        self.token_requests = 0

    def best_offer(self, ean):
        if time.monotonic() >= self.expires_at - 30:
            self.token, lifetime = authenticate(os.environ.get('BOL_API_CLIENT_ID'), os.environ.get('BOL_API_CLIENT_SECRET'))
            self.expires_at = time.monotonic() + lifetime
            self.token_requests += 1
        if self.last_request is not None:
            time.sleep(max(0, .25 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        url = CATALOG_URL + ean + '/offers/best?country-code=NL'
        req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/json', 'Accept-Language': 'nl'})
        try:
            return request_json(req, 'best_offer')
        except ReviewError as exc:
            if exc.status == 404:
                return None
            raise  # No blind token retry, rate-limit retry or partial publication.


def verified_ean(product):
    value = str(product.get('ean') or '').strip()
    if not re.fullmatch(r'\d{8}|\d{12,14}', value):
        raise FeedError('invalid_existing_barcode')
    gtin = strict_normalize_gtin(value)
    if not gtin:
        raise FeedError('invalid_existing_barcode')
    registered = product.get('gtin_normalized')
    if registered and registered != gtin:
        raise FeedError('existing_barcode_conflict')
    if not is_vinyl_format(product.get('format_label')):
        raise FeedError('existing_format_not_vinyl')
    return value, gtin


def api_ean(gtin):
    # UPC-A and leading-zero GTIN-14 share the same GS1 identity as EAN-13.
    # A nonzero packaging indicator cannot be dropped to invent a consumer EAN.
    if len(gtin) != 14 or not gtin.startswith('0'):
        raise FeedError('api_requires_consumer_ean13')
    return gtin[1:]


def normalize_offer(product, offer, site_id, captured):
    ean, gtin = verified_ean(product)
    if not isinstance(offer, dict):
        raise FeedError('invalid_offer_schema')
    response_ean = str(offer.get('ean') or '')
    if not re.fullmatch(r'\d{8}|\d{12,14}', response_ean) or strict_normalize_gtin(response_ean) != gtin:
        raise FeedError('response_barcode_mismatch')
    if offer.get('countryCode') != 'NL':
        raise FeedError('wrong_offer_market')
    if offer.get('condition') != 'NEW':
        raise FeedError('condition_not_proven_new')
    if not isinstance(offer.get('isPreOrder'), bool):
        raise FeedError('unknown_preorder_state')
    if offer.get('currency', 'EUR') != 'EUR':
        raise FeedError('wrong_offer_currency')
    price = amount(offer.get('price'))
    raw_url = str(offer.get('url') or '')
    url = urllib.parse.urlsplit(raw_url)
    if url.scheme == 'https' and url.netloc == 'partner.bol.com' and url.path == '/click/click':
        destinations = urllib.parse.parse_qs(url.query).get('url', [])
        if len(destinations) != 1:
            raise FeedError('invalid_affiliate_destination')
        raw_url = destinations[0]
    parts = urllib.parse.urlsplit(raw_url)
    canonical = product_link(urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, '', '')), 'NL')
    product_id = canonical.rstrip('/').rsplit('/', 1)[-1]
    delivery = str(offer.get('deliveryDescription') or '')
    availability = 'preorder' if offer['isPreOrder'] else 'unknown'
    if not offer['isPreOrder'] and delivery.casefold().startswith('op voorraad.'):
        availability = 'in_stock'
    return {'ean': ean, 'gtin': gtin, 'product_id': product_id,
            'title': str(product.get('title') or 'Vinyl ' + ean), 'country': 'NL',
            'price': price, 'currency': 'EUR', 'condition': 'NEW',
            'availability': availability, 'delivery_description': delivery,
            'min_delivery_date': offer.get('minDeliveryDate'),
            'max_delivery_date': offer.get('maxDeliveryDate'),
            'seller': 'unknown', 'shipping': None, 'shipping_status': 'unknown',
            'product_url': affiliate_link(canonical, 'NL', site_id),
            'canonical_url': canonical, 'captured_at': captured.isoformat(),
            'source': 'bol_marketing_api_best_offer'}


def load_targets(dsn, limit, cursor=None, sample=False):
    if cursor:
        uuid.UUID(cursor)  # Never interpolate an arbitrary cursor into SQL.
    with psycopg.connect(dsn, prepare_threshold=None) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute('set transaction read only')
        cur.execute('''select count(*) as count from public.products
            where ''' + VINYL_SQL + ' and ean is not null', (list(VINYL_FORMATS),))
        total = cur.fetchone()['count']
        # Use canonical format evidence; no title-based matching/new products.
        sql = '''select id,ean,gtin_normalized,format_label,title from public.products
                 where ''' + VINYL_SQL + ' and ean is not null'
        values = [list(VINYL_FORMATS)]
        if sample:
            sql += ' and ean=any(%s)'
            values.append(list(EANS))
        elif cursor:
            sql += ' and id>%s::uuid'
            values.append(cursor)
        sql += ' order by id limit %s'
        values.append(limit)
        cur.execute(sql, values)
        rows = cur.fetchall()
        wrapped = False
        if not rows and cursor and not sample:
            # Start a new pass only after reaching the end of the stable UUID order.
            cur.execute('''select id,ean,gtin_normalized,format_label,title from public.products
                where ''' + VINYL_SQL + ' and ean is not null order by id limit %s', (list(VINYL_FORMATS), limit))
            rows, wrapped = cur.fetchall(), True
    return rows, wrapped, total


def run(dsn, limit=20, write=False, sample=False, site_id='', progress=STATE_PATH):
    started = datetime.now(timezone.utc)
    plan = {'status': 'blocked', 'country': 'NL', 'database_writes': 0, 'offers': [],
            'errors': [], 'captured_at': started.isoformat(), 'source': 'bol_marketing_api',
            'complete_feed': False, 'scope': 'existing_vinyl_prices', 'sample': sample,
            'requested': limit, 'checked': 0, 'skipped': {}, 'token_requests': 0}
    client, skips = None, Counter()
    try:
        if not re.fullmatch(r'\d+', site_id):
            raise FeedError('missing_or_invalid_site_id')
        cursor = None
        if progress.exists() and not sample:
            state = json.loads(progress.read_text())
            cursor = state.get('cursor')
            if state.get('country') != 'NL':
                raise FeedError('wrong_progress_market')
        products, wrapped, total = load_targets(dsn, limit, cursor, sample)
        plan['wrapped'] = wrapped
        plan['eligible_catalogue'] = total
        client = Client()
        for product in products:
            try:
                ean, gtin = verified_ean(product)
                response = client.best_offer(api_ean(gtin))
                plan['checked'] += 1
                if response is None:
                    skips['no_offer_404'] += 1
                    continue
                plan['offers'].append(normalize_offer(product, response, site_id, started))
            except FeedError as exc:
                skips[str(exc)] += 1
        plan['skipped'] = dict(skips)
        plan['token_requests'] = client.token_requests
        validation_skips = sum(n for reason, n in skips.items() if reason not in {
            'no_offer_404', 'condition_not_proven_new', 'invalid_existing_barcode', 'existing_format_not_vinyl', 'api_requires_consumer_ean13'})
        if products and validation_skips / len(products) > .1:
            raise FeedError('widespread_offer_validation_failure')
        # Publication helper enforces market shop/shipping contracts, barcode
        # uniqueness, transactional writes and independent committed verification.
        if write and plan['offers']:
            plan['database_writes'] = None
            stats = publish(plan, dsn, {'NL': SHOP_ID}, approved=True, existing_only=True)
            plan['database'] = stats
            plan['database_writes'] = stats['updated_offers']
        if write and not sample and products:
            # Advance only after the complete batch succeeds. Not-found/unknown
            # items advance too, preventing starvation of later EANs.
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps({'country': 'NL', 'cursor': str(products[-1]['id']),
                'updated_at': datetime.now(timezone.utc).isoformat(), 'batch_size': len(products)}, indent=2) + '\n')
        plan['status'] = 'success' if products else 'empty_catalogue'
    except ReviewError as exc:
        plan['errors'].append({'stage': exc.stage, 'reason': exc.reason, 'http_status': exc.status})
        if 'ean' in locals():
            plan['failed_ean'] = ean
    except FeedError as exc:
        plan['errors'].append({'reason': str(exc)})
    except (psycopg.Error, ValueError, OSError):
        # Do not print raw DSNs, network exceptions or arbitrary state contents.
        plan['errors'].append({'reason': 'database_or_local_validation_failed'})
    finally:
        plan['skipped'] = dict(skips)
        if client is not None:
            plan['token_requests'] = client.token_requests
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--sample', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.limit <= 2000:
        parser.error('limit must be between 1 and 2000')
    result = run(os.environ.get('DATABASE_URL', ''), args.limit, args.write, args.sample,
                 os.environ.get('BOL_SITE_ID', ''))
    directory = Path('output/bol-api-prices')
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'review.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
    summary = {k: v for k, v in result.items() if k != 'offers'}
    message = json.dumps(summary, default=str).replace('%', '%25').replace('\n', '%0A').replace('\r', '%0D')
    print('::notice title=Bol NL price result::' + message, flush=True)
    for offer in result['offers'][:10]:
        sample = {k: offer[k] for k in ('ean', 'title', 'country', 'price', 'currency', 'condition', 'availability', 'canonical_url')}
        print('::notice title=Bol NL price sample::' + json.dumps(sample).replace('%', '%25').replace('\n', '%0A').replace('\r', '%0D'), flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
            display = dict(summary, offer_samples=result['offers'][:10], offer_count=len(result['offers']))
            handle.write('### Bol NL prices\n\n```json\n' + json.dumps(display, indent=2, default=str) + '\n```\n')
    return 0 if result['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
