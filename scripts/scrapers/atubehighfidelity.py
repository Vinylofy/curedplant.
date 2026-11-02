"""Read-only A Tube album pilot: listing prices first, optional detail enrichment.

Uses the shop's public load-more interface, not WordPress administration APIs.
No database imports/writes, publication, scheduling or invented barcodes.
"""
import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, urlencode, parse_qs

from bs4 import BeautifulSoup
from scripts.importers.common import strict_normalize_gtin
from scripts.workers.album_offer_sources import Transport, approved_url, norm, same_page

DOMAIN = 'atube-highfidelity.nl'
CATALOGUE = 'https://www.atube-highfidelity.nl/product-category/vinyl/?atube_cat=vinyl'
AJAX = 'https://www.atube-highfidelity.nl/wp-admin/admin-ajax.php'
ACTION = 'atube_cs_shop_load_more'
FIELDS = ('source_product_id', 'source_url', 'artist_raw', 'album_raw', 'title_raw',
          'price', 'currency', 'availability', 'format_status', 'condition_status',
          'ean_raw', 'ean_status', 'route', 'listing_observed_at', 'detail_status',
          'status', 'detail_observed_at', 'detail_price_crosscheck', 'gtin14', 'offer_url')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def money(value):
    try:
        price = Decimal(str(value).replace('€', '').replace(' ', '').replace('\xa0', '').replace(',', '.'))
        return str(price.quantize(Decimal('.01'))) if price.is_finite() and price > 0 else None
    except (InvalidOperation, ValueError):
        return None


def article_price(area):
    values = {money(n.get_text('', strip=True)) for n in area.select('.woocommerce-Price-amount') if not n.find_parent('del')}
    values.discard(None)
    return next(iter(values)) if len(values) == 1 else None


def labels(title):
    # Only explicit shop separators; never split ordinary hyphens in artist names.
    parts = re.split(r'\s+[-–—|]\s+', title, maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (None, None)


def product_url(url):
    approved_url(url, DOMAIN)
    parts = urlsplit(url)
    options = parse_qs(parts.query, keep_blank_values=True)
    if not re.fullmatch(r'/product/[^/]+/?', parts.path) or any(
            not re.fullmatch(r'attribute_[a-z0-9_-]+', name) or len(values) != 1 or not values[0] or len(values[0]) > 100
            for name, values in options.items()):
        raise ValueError('not_an_own_product_url')
    return url


def parse_listing(body, observed_at):
    soup = BeautifulSoup(body, 'html.parser')
    rows = []
    for card in soup.select('[data-atube-product-card]'):
        title = card.select_one('[data-atube-product-card-title]')
        link = card.select_one('[data-atube-product-card-link][href]')
        if not title or not link:
            raise ValueError('listing_identity_missing')
        name = title.get_text(' ', strip=True)
        artist, album = labels(name)
        price_area = card.select_one('[data-atube-product-card-price]')
        price = article_price(price_area) if price_area else None
        declared = money(card.get('data-price'))
        if price and price != declared:
            raise ValueError('listing_visible_attribute_price_conflict')
        cats = (card.get('data-cats') or '').split(',')
        physical = 'non_vinyl' if re.search(r'\b(?:CD|DVD|BLU[- ]?RAY|SACD|CASSETTE)\b', name, re.I) else ('vinyl' if 'vinyl' in cats else 'unknown')
        used = bool(re.search(r'\b(?:tweedehands|2e\s*hands|second[- ]hand|pre[- ]owned|occasion|ex[- ]demo)\b', name, re.I))
        row = dict(source_product_id=card.get('data-atube-product-id'), source_url=product_url(link['href']),
                   title_raw=name, artist_raw=artist, album_raw=album, price=price, currency='EUR',
                   availability='unknown', format_status=physical, condition_status='used' if used else 'new',
                   condition_basis='explicit_used_title' if used else 'no_used_signal_policy',
                   ean_raw=None, ean_status='EAN_NOT_CHECKED', route='ARTIST_TITLE_PENDING',
                   price_source='listing', listing_observed_at=observed_at, detail_status='not_sampled')
        row['review_reasons'] = [reason for condition, reason in ((not price, 'no_visible_positive_article_price'),
                                   (physical != 'vinyl', 'non_vinyl_or_unproven'), (used, 'secondhand'),
                                   (not artist or not album, 'artist_album_boundary_unproven')) if condition]
        rows.append(row)
    return rows


def load_more_config(body):
    soup = BeautifulSoup(body, 'html.parser')
    wrap = soup.select_one('[data-atube-shop-overview]')
    match = re.search(r'var\s+atubeShopOverviewParams\s*=\s*(\{[^\n]+?\});', body)
    if not wrap or not match or wrap.get('data-atube-prefilter-cat') != 'vinyl':
        raise ValueError('vinyl_pagination_contract_missing')
    config = json.loads(match.group(1))
    if config.get('ajaxUrl') != AJAX or config.get('action') != ACTION or not config.get('nonce'):
        raise ValueError('unreviewed_load_more_endpoint')
    return config, int(wrap['data-atube-shop-result-total']), int(wrap['data-atube-load-offset'])


class AtubeTransport(Transport):
    def more(self, config, offset):
        approved_url(AJAX, DOMAIN)
        if not self.robot or not self.robot.can_fetch(self.session.headers['User-Agent'], AJAX):
            raise ValueError('robots_disallow_load_more')
        time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        data = dict(action=ACTION, nonce=config['nonce'], offset=str(offset), per_page='24',
                    thumbs='no', swatches='yes', sort='relevant', filter_cat='vinyl')
        with self.session.post(AJAX, data=data, timeout=20, allow_redirects=False, stream=True) as response:
            self.requests.append({'url': AJAX, 'method': 'POST', 'offset': offset, 'status': response.status_code})
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('load_more_redirect_or_empty')
            raw = response.raw.read(2_000_001, decode_content=True)
            if len(raw) > 2_000_000:
                raise ValueError('load_more_size_limit')
            result = json.loads(raw)
            self.requests[-1]['sha256'] = hashlib.sha256(raw).hexdigest()
            if result.get('success') is not True or not isinstance(result.get('data'), dict):
                raise ValueError('load_more_rejected')
            return result['data']


def catalogue(transport, max_pages, observed_at, records=None):
    body = transport.get(CATALOGUE)
    config, total, offset = load_more_config(body)
    rows = records if records is not None else []
    rows.extend(parse_listing(body, observed_at))
    seen = {r['source_url'] for r in rows}
    if not rows or len(seen) != len(rows) or offset != len(rows):
        raise ValueError('initial_catalogue_empty_duplicate_or_offset_mismatch')
    pages = 1
    reason = 'end_of_catalogue' if offset >= total else 'pilot_page_limit'
    while offset < total and pages < max_pages:
        page = transport.more(config, offset)
        fresh = parse_listing(page.get('html', ''), observed_at)
        if not fresh:
            if page.get('has_more'):
                raise ValueError('empty_page_claims_more')
            reason = 'empty_last_page'
            break
        urls = {r['source_url'] for r in fresh}
        if len(urls) != len(fresh) or urls & seen:
            raise ValueError('pagination_repeated_product')
        loaded = int(page['loaded'])
        if loaded != offset + len(fresh) or int(page['total']) != total:
            raise ValueError('pagination_offset_or_total_changed')
        rows.extend(fresh)
        seen.update(urls)
        offset = loaded
        pages += 1
        if not page.get('has_more'):
            if offset < total:
                raise ValueError('premature_catalogue_end')
            reason = 'end_of_catalogue'
            break
        if offset >= total:
            raise ValueError('pagination_more_beyond_total')
    visible = BeautifulSoup(body, 'html.parser').get_text(' ', strip=True)
    shipping = re.search(r'In heel Nederland en België gratis bezorging bij artikelen boven de\s+150,- euro\.', visible)
    return rows, dict(reported_total=total, loaded=len(rows), pages=pages,
                      complete=offset >= total, stop_reason=reason,
                      shipping_evidence={'source_url': CATALOGUE, 'observed_at': observed_at,
                          'source_sha256': hashlib.sha256(body.encode()).hexdigest(),
                          'quote': shipping.group(0) if shipping else None})


def parse_detail(body, row, observed_at):
    soup = BeautifulSoup(body, 'html.parser')
    canonical = soup.select_one('link[rel="canonical"]')
    if not canonical or not same_page(product_url(canonical.get('href', '')), row['source_url']):
        raise ValueError('detail_canonical_mismatch')
    scope = soup.select_one('div.product[id="product-' + str(row['source_product_id']) + '"]')
    if not scope:
        raise ValueError('own_product_id_scope_missing')
    if 'product_cat-vinyl' not in scope.get('class', []) or re.search(r'\b(?:CD|DVD|BLU[- ]?RAY|SACD|CASSETTE)\b', row['title_raw'], re.I):
        raise ValueError('own_vinyl_format_unproven')
    for other in scope.select('.related, .products, .upsells, .cross-sells'):
        other.decompose()
    heading = scope.select_one('h1.product_title')
    if not heading or norm(heading.get_text(' ', strip=True)) != norm(row['title_raw']):
        raise ValueError('detail_listing_title_mismatch')
    prices = scope.select('.bde-wooproductprice .price')
    detail_price = article_price(prices[0]) if len(prices) == 1 else None
    variation = None
    form = scope.select_one('form.variations_form[data-product_variations]')
    if form:
        choices = json.loads(form['data-product_variations'])
        if not isinstance(choices, list):
            raise ValueError('public_variant_data_unavailable')
        choices = [v for v in choices if v.get('variation_is_active') is True
                   and v.get('variation_is_visible') is True and v.get('is_purchasable') is True
                   and v.get('attributes') and all(value and (' ' + norm(value) + ' ') in (' ' + norm(row['title_raw']) + ' ')
                       for value in v['attributes'].values())]
        if len(choices) != 1:
            raise ValueError('selected_variant_unproven')
        variation = choices[0]
        requested = parse_qs(urlsplit(row['source_url']).query)
        if requested and requested != {k: [v] for k, v in variation['attributes'].items()}:
            raise ValueError('requested_variant_conflict')
        detail_price = money(variation.get('display_price'))
    if not row['price'] or detail_price != row['price']:
        raise ValueError('detail_listing_price_conflict')
    specs = {}
    tables = soup.select('.woocommerce-Tabs-panel--common_tab #product-attribute-specs-table')
    if len(tables) > 1:
        raise ValueError('own_specifications_ambiguous')
    for tr in tables[0].select('tr') if tables else []:
        cells = tr.find_all(['td', 'th'], recursive=False)
        if len(cells) == 2:
            specs[norm(cells[0].get_text(' ', strip=True))] = cells[1].get_text(' ', strip=True)
    raw_codes = [v for k, v in specs.items() if re.fullmatch(r'ean(?: code)?|barcode|upc|gtin(?:8|12|13|14)?', k) and v.strip()]
    codes = {strict_normalize_gtin(code) for code in raw_codes}
    if None in codes or '' in codes or len(codes) > 1:
        raise ValueError('invalid_or_conflicting_labelled_barcode')
    if variation and codes:
        raise ValueError('parent_barcode_not_proven_for_selected_variant')
    artist = specs.get('artiest en') or specs.get('artiest') or specs.get('artist')
    if artist and row['artist_raw'] and norm(artist) != norm(row['artist_raw']):
        raise ValueError('detail_artist_conflict')
    state = specs.get('conditie') or specs.get('staat')
    used = row['condition_status'] == 'used' or bool(state and norm(state) not in ('nieuw', 'new', 'sealed'))
    classes = scope.get('class', [])
    stock = 'out_of_stock' if 'outofstock' in classes else ('preorder' if 'onbackorder' in classes else ('in_stock' if 'instock' in classes else 'unknown'))
    if variation:
        stock = 'preorder' if variation.get('backorders_allowed') else ('in_stock' if variation.get('is_in_stock') is True else ('out_of_stock' if variation.get('is_in_stock') is False else 'unknown'))
    ean = re.sub(r'\D', '', raw_codes[0]) if raw_codes else None
    result = {**row, 'artist_raw': artist or row['artist_raw'], 'ean_raw': ean,
              'gtin14': next(iter(codes)) if codes else None,
              'ean_status': 'EAN_AVAILABLE' if codes else 'EAN_NOT_FOUND',
              'route': 'EAN' if codes else 'ARTIST_TITLE', 'availability': stock,
              'condition_status': 'used' if used else 'new', 'condition_basis': 'explicit_attribute' if state else row['condition_basis'],
              'detail_status': 'ok', 'detail_observed_at': observed_at, 'detail_price_crosscheck': detail_price,
              'source_specs': specs, 'source_sha256': hashlib.sha256(body.encode()).hexdigest(),
              'ean_check_scope': 'own labelled product specifications only; never SKU, URL, images or related products'}
    if variation:
        result['selected_variant'] = {k: variation.get(k) for k in ('variation_id', 'attributes', 'display_price', 'is_in_stock')}
        result['offer_url'] = row['source_url'] + '?' + urlencode(variation['attributes'])
    result['review_reasons'] = row['review_reasons'] + (['secondhand'] if used else []) + (['stock_unproven'] if stock == 'unknown' else [])
    result['status'] = 'review' if result['review_reasons'] else 'validated'
    return result


def verify_album_source(body, queue_row):
    """Adapter for the existing private album queue; does not enqueue or write."""
    source = queue_row['source_input']
    if source.get('currency') != 'EUR':
        raise ValueError('source_currency_conflict')
    observed = source.get('listing_observed_at')
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(observed)).total_seconds()
    except (ValueError, TypeError):
        raise ValueError('fresh_listing_required') from None
    if not 0 <= age <= 48 * 3600 or source.get('price_source') not in ('listing', 'catalogue'):
        raise ValueError('fresh_listing_required')
    artist, album = labels(source['title_raw'])
    if not artist or not album:
        raise ValueError('artist_album_boundary_unproven')
    title = source['title_raw']
    used = bool(re.search(r'\b(?:tweedehands|2e\s*hands|second[- ]hand|pre[- ]owned|occasion|ex[- ]demo)\b', title, re.I))
    parent_id = source.get('parent_product_id') or queue_row['source_product_id']
    row = dict(source_url=product_url(queue_row['product_url']), source_product_id=parent_id,
               title_raw=title, artist_raw=artist, album_raw=album, price=money(source.get('price')),
               currency='EUR', listing_observed_at=observed, condition_status='used' if used else 'new',
               condition_basis='no_used_signal_policy', format_status='vinyl', review_reasons=['secondhand'] if used else [])
    result = parse_detail(body, row, stamp())
    if result['status'] != 'validated':
        raise ValueError('source_requires_review')
    if result.get('selected_variant'):
        variant_id = str(result['selected_variant']['variation_id'])
        if str(queue_row['source_product_id']) not in (str(parent_id), variant_id):
            raise ValueError('source_variant_identity_conflict')
        result.update(parent_product_id=str(parent_id), source_product_id=variant_id)
    return {**result, 'domain': DOMAIN, 'product_url': result.get('offer_url', row['source_url']),
            'source_title': title, 'artist': result['artist_raw'], 'label': result['artist_raw'] + ' ' + album,
            'observed_at': result['detail_observed_at'], 'price_basis': 'fresh_listing_crosschecked_own_html'}


def run(transport, mode, pages, detail_limit):
    output = dict(shop=DOMAIN, created_at=stamp(), mode=mode, database_writes=0,
                  status='running', records=[], requests=transport.requests)
    try:
        transport.start(CATALOGUE)
        rows, pagination = catalogue(transport, pages, output['created_at'], output['records'])
        output.update(records=rows, pagination=pagination)
        if mode == 'details':
            for row in [r for r in rows if not r['review_reasons']][:detail_limit]:
                try:
                    detail = parse_detail(transport.get(row['source_url']), row, stamp())
                    row.update(detail)
                except ValueError as error:
                    row.update(detail_status='review', status='review', detail_reason=str(error))
                except Exception as error:
                    row.update(detail_status='technical_error', status='review', detail_reason=str(error))
                    raise
        valid = any(r.get('status') == 'validated' for r in rows) if mode == 'details' else any(not r['review_reasons'] for r in rows)
        output['status'] = 'success' if valid else 'review_required'
        if not valid:
            output['error'] = 'no_verified_detail' if mode == 'details' else 'no_eligible_listing_price'
    except Exception as error:
        # An access failure stops this shop; retain the successfully captured listing.
        output.update(status='failed', error=type(error).__name__ + ': ' + str(error))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('prices', 'details'), required=True)
    parser.add_argument('--pages', type=int, default=2)
    parser.add_argument('--detail-limit', type=int, default=5)
    parser.add_argument('--output', type=Path, default=Path('output/atubehighfidelity'))
    args = parser.parse_args()
    if not 0 <= args.pages <= 10 or not 1 <= args.detail_limit <= 25:
        parser.error('Limits: 0=complete catalogue or 1..10 pages; 1..25 details')
    transport = AtubeTransport(DOMAIN)
    try:
        result = run(transport, args.mode, args.pages or 1000, args.detail_limit)
    finally:
        transport.close()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    with (args.output / 'products.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(result['records'])
    counts = {}
    for row in result['records']:
        state = row.get('status', 'listing_review' if row['review_reasons'] else 'listing_pending_details')
        counts[state] = counts.get(state, 0) + 1
    print(json.dumps({k: v for k, v in result.items() if k not in ('records', 'requests')} | {'records': len(result['records']), 'counts': counts}))
    return 0 if result['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
