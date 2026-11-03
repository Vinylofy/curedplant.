"""Conservative RareVinyl USF staging preview. This module never writes to a DB."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4
from scripts.importers.common import strict_normalize_gtin
from scripts.scrapers.usf.core.staging import build_stage_item


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
