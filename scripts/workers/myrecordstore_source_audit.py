"""Read-only coverage check of the production My Record Store price collector."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import psycopg
import requests

from scripts.workers.price_evidence import assess, url_key

SHOP = 'd066e318-b6a4-4780-8893-2a4b1b2d1d25'


def main():
    with psycopg.connect(os.environ['DATABASE_URL'], prepare_threshold=None) as conn:
        conn.execute('set transaction read only')
        registered = conn.execute(
            'select product_url from public.prices where shop_id=%s and is_active=true',
            (SHOP,),
        ).fetchall()
    known = {url_key(row[0]) for row in registered}
    from scripts.workers.myrecordstore_targets import registered_offers
    from scripts.scrapers.usf.jobs import refresh_myrecordstore_listing_prices as source
    from datetime import datetime, timezone
    from urllib.parse import urlencode
    targets = registered_offers()[:5]
    searches = []
    session = requests.Session()
    session.headers.update(source.HEADERS)
    for target in targets:
        url = 'https://myrecordstore.nl/item/search?' + urlencode({'q': target['ean'], 'type': 'LP'})
        response = session.get(url, timeout=45)
        response.raise_for_status()
        links, offers = source.parse_listing_page(response.text, listing_url=url, page=1, seen_at=datetime.now(timezone.utc))
        searches.append({'requested_id': target['source_product_id'], 'ean': target['ean'],
                         'found_ids': [x.source_product_id for x in links][:12],
                         'matched': any(x.source_product_id == target['source_product_id'] for x in links)})
    print('::notice title=My Record Store targeted search check::' + json.dumps(searches))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
