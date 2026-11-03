"""Bounded, read-only RareVinyl source pilot; no database writes or publication."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import argparse
import json
import re
import time
from urllib.parse import quote, urlsplit
from urllib.robotparser import RobotFileParser

import requests

BASE = 'https://eu.rarevinyl.com'
COLLECTION = '/collections/brand-new-factory-sealed-vinyl-records-and-cds/products.json'
UA = 'VinylofyRareVinylResearch/1.0 (+https://vinylofy.com)'
VINYL = re.compile(r'\b(?:vinyl|(?:\d\s*[-x]?\s*)?lp|picture\s+disc|[1270]+[ -]?inch)\b', re.I)
NON_VINYL = re.compile(r'\b(?:\d+\s*)?(?:cd|dvd|cassette|blu[ -]?ray)\b', re.I)


def valid_gtin(value):
    code = str(value or '').strip()
    if not code.isascii() or not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return None
    total = sum(int(ch) * (3 if i % 2 == 0 else 1) for i, ch in enumerate(reversed(code[:-1])))
    return code if (10 - total % 10) % 10 == int(code[-1]) else None


def listing(product):
    handle = product.get('handle') or ''
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', handle):
        raise ValueError('unsafe_product_handle')
    variants = product.get('variants') or []
    if len(variants) != 1:
        raise ValueError('ambiguous_variants')
    variant = variants[0]
    try:
        price = Decimal(str(variant['price']))
        if not price.is_finite() or price <= 0:
            raise ValueError()
    except (KeyError, ValueError, InvalidOperation):
        raise ValueError('invalid_price')
    title = str(product.get('title') or '').strip()
    artist = str(product.get('vendor') or '').strip()
    album = title[len(artist):].strip(' -–—') if artist and title.casefold().startswith(artist.casefold()) else ''
    tags = [str(t) for t in product.get('tags') or []]
    signals = ' '.join([title, *tags])
    fmt = 'vinyl' if VINYL.search(signals) and not NON_VINYL.search(title) else 'other_or_unknown'
    return {'source_id': str(product['id']), 'variant_id': str(variant['id']),
            'url': BASE + '/products/' + handle, 'artist': artist or None,
            'title_raw': title, 'album_raw': album or None, 'price': str(price),
            'compare_at_price': variant.get('compare_at_price'), 'currency': 'EUR',
            'availability': 'in_stock' if variant.get('available') is True else 'out_of_stock' if variant.get('available') is False else 'unknown',
            'sealed_candidate': any(t.casefold() == 'sealed' for t in tags),
            'new_tag': any(t.casefold() == 'wholesalenew' for t in tags),
            'format_status': fmt, 'condition_status': 'unknown', 'barcode': valid_gtin(variant.get('barcode')),
            'image_url': (product.get('images') or [{}])[0].get('src'),
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'publication_blocked': True, 'block_reason': 'market_tax_and_condition_unverified'}


def enrich(row, product):
    variants = product.get('variants') or []
    if str(product.get('id')) != row['source_id'] or len(variants) != 1 or str(variants[0].get('id')) != row['variant_id']:
        raise ValueError('detail_identity_conflict')
    variant = variants[0]
    detail_price = Decimal(str(variant.get('price'))) / 100
    if detail_price != Decimal(row['price']):
        raise ValueError('listing_detail_price_conflict')
    result = dict(row)
    result.update(barcode=valid_gtin(variant.get('barcode')), detail_checked_at=datetime.now(timezone.utc).isoformat(),
                  detail_price=str(detail_price), condition_status='unknown')
    return result


def fetch(session, robots, url, params=None):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'eu.rarevinyl.com' or not robots.can_fetch(UA, url):
        raise ValueError('robots_or_host_blocked')
    for attempt in range(3):
        try:
            response = session.get(url, params=params, timeout=25, allow_redirects=False)
            if response.status_code in (401, 403, 429):
                raise RuntimeError('access_blocked_%s' % response.status_code)
            if response.status_code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError('unexpected_redirect')
            return response.json()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError('request_failed')


def run(pages, details, delay):
    if not 1 <= pages <= 2 or not 0 <= details <= 10 or delay < 1:
        raise ValueError('pilot bounds: pages 1..2, details 0..10, delay >=1s')
    session = requests.Session()
    session.headers.update({'User-Agent': UA, 'Accept-Language': 'nl-NL,nl;q=0.9'})
    response = session.get(BASE + '/robots.txt', timeout=25, allow_redirects=False)
    if response.status_code != 200:
        raise RuntimeError('robots_unavailable_%s' % response.status_code)
    robots = RobotFileParser()
    robots.parse(response.text.splitlines())
    rows, errors, duplicates, page_ids = {}, [], 0, set()
    for page in range(1, pages + 1):
        time.sleep(delay)
        data = fetch(session, robots, BASE + COLLECTION, {'limit': 50, 'page': page})
        products = data.get('products')
        if not isinstance(products, list):
            raise ValueError('invalid_listing_response')
        ids = tuple(str(p.get('id')) for p in products)
        if not ids:
            break
        if ids in page_ids:
            raise ValueError('repeated_page')
        page_ids.add(ids)
        for p in products:
            try:
                row = listing(p)
                if row['source_id'] in rows:
                    duplicates += 1
                else:
                    rows[row['source_id']] = row
            except (KeyError, ValueError) as exc:
                errors.append({'source_id': str(p.get('id')), 'reason': str(exc)})
    detail_count = 0
    detail_attempts = 0
    for row in list(rows.values()):
        if detail_attempts >= details:
            break
        if row['format_status'] != 'vinyl' or not row['sealed_candidate']:
            continue
        detail_attempts += 1
        try:
            time.sleep(delay)
            detail = fetch(session, robots, row['url'] + '.js')
            rows[row['source_id']] = enrich(row, detail)
            detail_count += 1
        except (ValueError, KeyError, InvalidOperation) as exc:
            errors.append({'source_id': row['source_id'], 'reason': str(exc)})
    records = list(rows.values())
    return {'status': 'research_only', 'database_writes': 0, 'publication_blocked': True,
            'summary': {'discovered': len(records), 'valid_prices': len(records),
                        'sealed_candidates': sum(r['sealed_candidate'] for r in records),
                        'confirmed_new': 0, 'detail_checked': detail_count, 'detail_attempts': detail_attempts,
                        'valid_barcodes': sum(bool(r['barcode']) for r in records),
                        'without_barcode': sum(not r['barcode'] for r in records),
                        'missing_artist_or_title': sum(not r['artist'] or not r['album_raw'] for r in records),
                        'duplicates': duplicates, 'errors': len(errors), 'quarantine': len(errors)},
            'errors': errors, 'records': records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, default=1)
    parser.add_argument('--details', type=int, default=0)
    parser.add_argument('--delay', type=float, default=1.5)
    parser.add_argument('--output', default='rarevinyl-pilot.json')
    args = parser.parse_args()
    result = run(args.pages, args.details, args.delay)
    with open(args.output, 'w', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result['summary']))

if __name__ == '__main__':
    main()
