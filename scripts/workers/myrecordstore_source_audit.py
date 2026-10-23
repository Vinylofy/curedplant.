"""Read-only coverage check of the production My Record Store price collector."""
import json
import os
import re
from urllib.parse import urljoin, urlsplit
from pathlib import Path
import subprocess
import sys
import tempfile

import psycopg
import requests
from bs4 import BeautifulSoup

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
    with tempfile.TemporaryDirectory() as directory:
        evidence = Path(directory) / 'prices.jsonl'
        env = dict(os.environ, CUREDPLANT_PRICE_EVIDENCE=str(evidence), DATABASE_URL='',
                   PGOPTIONS='-c default_transaction_read_only=on')
        result = subprocess.run([
            sys.executable, '-u', '-m',
            'scripts.scrapers.usf.jobs.refresh_myrecordstore_listing_prices',
            '--max-pages', '0',
        ], env=env, check=False)
        records = [json.loads(line) for line in evidence.read_text().splitlines()] if evidence.exists() else []
    prices, assessment = assess(records)
    report = {
        'database_writes': 0,
        'status': assessment['status'] if result.returncode == 0 else 'red',
        'source_returncode': result.returncode,
        'registered_active_prices': len(registered),
        'current_listing_prices': len(prices),
        'registered_prices_found': sum(url_key(row['source_url']) in known for row in prices),
        'errors': assessment['errors'],
        'samples': [{'url': row['source_url'], 'price': row['price']} for row in prices[:3]],
    }
    response = requests.get('https://myrecordstore.nl/item/search?tags=Voorraad&type=LP', timeout=45)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    controls = [str(x)[:1500] for x in soup.select('input,button') if any(w in str(x).lower() for w in ('search', 'zoek', 'zoeken'))][:5]
    scripts = []
    for script in soup.select('script'):
        content = script.get_text()
        index = content.find('/item/search')
        if index >= 0:
            scripts.append(content[max(0,index-300):index+800])
    for tag in soup.select('script[src]')[:15]:
        asset = urljoin(response.url, tag['src'])
        if urlsplit(asset).netloc != 'myrecordstore.nl':
            continue
        javascript = requests.get(asset, timeout=20)
        javascript.raise_for_status()
        for match in re.finditer(r'.{0,100}/item/search.{0,250}', javascript.text):
            scripts.append(match.group(0))
    scripts = scripts[:6]
    print('::notice title=Public search controls::' + json.dumps({'controls': controls, 'scripts': scripts}).replace('%','%25'))
    text = json.dumps(report).replace('%', '%25').replace('\n', '%0A').replace('\r', '%0D')
    print('::notice title=My Record Store catalogue coverage audit::' + text)
    return 0 if report['status'] == 'green' else 1


if __name__ == '__main__':
    raise SystemExit(main())
