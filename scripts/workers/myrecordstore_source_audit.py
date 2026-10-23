"""Read-only comparison of recent arrivals and in-stock My Record Store pages."""
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs

import psycopg
from bs4 import BeautifulSoup
import requests

from scripts.scrapers.usf.jobs import refresh_myrecordstore_listing_prices as source
from scripts.workers.price_evidence import url_key

SHOP = 'd066e318-b6a4-4780-8893-2a4b1b2d1d25'


def main():
    with psycopg.connect(os.environ['DATABASE_URL'], prepare_threshold=None) as conn:
        conn.execute('set transaction read only')
        rows = conn.execute('select product_url,last_seen_at from public.prices where shop_id=%s and is_active=true', (SHOP,)).fetchall()
    known_urls = {url_key(row[0]) for row in rows}
    known_ids = {urlsplit(row[0]).path.rstrip('/').rsplit('/', 1)[-1] for row in rows}
    session = requests.Session()
    session.headers.update(source.HEADERS)
    report = {'database_writes': 0, 'registered_active_prices': len(rows), 'sources': []}
    for scope in ('nieuw', 'op-voorraad'):
        url = f'https://myrecordstore.nl/item/{scope}?type=LP'
        response = session.get(url, timeout=45)
        response.raise_for_status()
        links, offers = source.parse_listing_page(response.text, listing_url=response.url, page=1,
            seen_at=datetime.now(timezone.utc))
        soup = BeautifulSoup(response.text, 'html.parser')
        pages = []
        for a in soup.select('a[href]'):
            parsed = urlsplit(source.normalize_url(a.get('href')))
            if parsed.path != f'/item/{scope}':
                continue
            page = parse_qs(parsed.query).get('page', [''])[0]
            if page.isdigit():
                pages.append(int(page))
        report['sources'].append({'scope': scope, 'url': response.url, 'first_page_products': len(links),
            'advertised_last_page': max(pages) if pages else None,
            'existing_url_matches': sum(url_key(x.source_url) in known_urls for x in links),
            'existing_numeric_id_matches': sum(source.source_product_id_from_url(x.source_url) in known_ids for x in links),
            'availability': {kind: sum(x.availability == kind for x in offers) for kind in ('in_stock', 'unknown', 'out_of_stock')},
            'sample_urls': [x.source_url for x in links[:3]]})
        time.sleep(1)
    text = json.dumps(report).replace('%', '%25').replace('\n', '%0A').replace('\r', '%0D')
    print('::notice title=My Record Store catalogue scope audit::' + text)


if __name__ == '__main__':
    main()
