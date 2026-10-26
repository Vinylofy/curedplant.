"""One read-only JPC index/page request; no database or GitHub credentials needed."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
from scripts.scrapers.usf.jobs import discover_jpc_vinyl as native


def collect(request):
    session = native.build_session()
    try:
        if request['kind'] == 'index':
            routes = native.merge_routes(native.parse_route_specs('default'),
                native.discover_route_index(session=session, timeout_seconds=25))
            return {'routes': [{'name': r.name, 'url': r.url} for r in routes]}
        route = native.RouteSpec(**request['route'])
        page = request['page']
        url = route.url if page == 1 else native.ff_page_url(route.url, page_number=page)
        if not url:
            raise ValueError('Unsupported category pagination')
        response = native.request_listing_page(session=session, route=route, url=url,
                                                page_number=page, timeout_seconds=25)
        if response.status_code in {404, 410} and page > 1:
            return {'terminal': True, 'signature': None, 'rows': [], 'source_products': 0}
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        ids = sorted({identifier for a in soup.find_all('a', href=True)
                      if (identifier := native.hnum_from_href(a.get('href')))})
        links = native.parse_listing_links(response.text, listing_url=response.url,
                                            route=route, page_number=page)
        rows = [{'kind': 'native_listing', 'source_url': link.source_url,
                 'price': link.payload.get('listing_price_raw'), 'currency': 'EUR',
                 'availability': link.payload.get('listing_availability'), 'raw': link.payload}
                for link in links]
        return {'terminal': not ids, 'source_products': len(ids), 'rows': rows,
                'signature': hashlib.sha256('\n'.join(ids).encode()).hexdigest() if ids else None,
                'captured_at': datetime.now(timezone.utc).isoformat()}
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = collect(json.loads(args.request.read_text()))
    args.output.write_text(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
