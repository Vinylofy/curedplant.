"""Export existing vinyl offer identities without giving the collector DB access."""
import os
from urllib.parse import urlsplit

import psycopg

from scripts.importers.common import strict_normalize_gtin
from scripts.workers.price_evidence import url_key


def registered_offers():
    with psycopg.connect(os.environ['DATABASE_URL'], prepare_threshold=None) as conn:
        conn.execute('set transaction read only')
        rows = conn.execute('''
            select pr.product_url, p.ean, p.gtin_normalized
            from public.prices pr
            join public.shops sh on sh.id=pr.shop_id
            join public.products p on p.id=pr.product_id
            where sh.domain='myrecordstore.nl' and pr.is_active=true
            order by pr.last_seen_at nulls first, pr.product_id
        ''').fetchall()
    targets = []
    for url, ean, normalized in rows:
        key = url_key(url)
        barcode = strict_normalize_gtin(normalized or ean)
        if key.startswith('myrecordstore.nl/item/lp/') and barcode:
            query_ean = str(ean or '').strip()
            if not query_ean.isdigit() or strict_normalize_gtin(query_ean) != barcode:
                query_ean = barcode[-13:]
            targets.append({'source_url': url, 'ean': query_ean,
                            'source_product_id': urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]})
    return targets
