"""Bounded Marketing Catalog API connectivity/schema review; never imports data."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = 'https://login.bol.com/token'
CATALOG_URL = 'https://api.bol.com/marketing/catalog/v1/products/'
# Existing vinyl EANs; these are probes, not an assertion of Bol availability.
EANS = ('0886922480287', '4018939545352', '3596974182769', '0889854344115',
        '0602567549499', '0885513028716', '0602475625551', '0888072785700',
        '0194111030220', '4251896109247')


class ReviewError(Exception):
    def __init__(self, stage, reason, status=None):
        self.stage, self.reason, self.status = stage, reason, status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(request, stage):
    # Never follow a redirect carrying Basic/Bearer authorization.
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ReviewError(stage, 'response_too_large')
        return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise ReviewError(stage, 'http_error', exc.code) from None
    except (socket.timeout, TimeoutError):
        raise ReviewError(stage, 'timeout') from None
    except (urllib.error.URLError, ssl.SSLError, OSError):
        raise ReviewError(stage, 'connection_failed') from None
    except (ValueError, UnicodeError):
        raise ReviewError(stage, 'invalid_json') from None


def schema_paths(value, prefix='', depth=0):
    """Field paths/types only: never publish response values or tokens."""
    if depth > 4:
        return []
    if isinstance(value, dict):
        result = []
        for key in sorted(value)[:40]:
            name = f'{prefix}.{key}' if prefix else key
            result.append({'field': name, 'type': type(value[key]).__name__})
            result.extend(schema_paths(value[key], name, depth + 1))
        return result[:120]
    if isinstance(value, list) and value:
        return schema_paths(value[0], prefix + '[]', depth + 1)
    return []


def review(client_id, client_secret):
    result = {'status': 'blocked', 'database_writes': 0, 'token_requests': 0,
              'authentication': 'not_tested', 'products': [], 'errors': []}
    if not client_id or not client_secret:
        result['errors'].append({'stage': 'configuration', 'reason': 'missing_api_credentials'})
        return result
    stage = 'authentication'
    try:
        credentials = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()
        request = urllib.request.Request(TOKEN_URL,
            data=urllib.parse.urlencode({'grant_type': 'client_credentials'}).encode(),
            headers={'Authorization': 'Basic ' + credentials, 'Accept': 'application/json',
                     'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
        result['token_requests'] = 1
        token_data = request_json(request, stage)
        token = token_data.get('access_token') if isinstance(token_data, dict) else None
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise ReviewError(stage, 'missing_or_invalid_access_token')
        result['authentication'] = 'success'
        for country in ('NL', 'BE'):
            for ean in EANS:
                stage = 'catalog'
                url = CATALOG_URL + ean + '?' + urllib.parse.urlencode({
                    'country-code': country, 'include-offer': 'true'})
                request = urllib.request.Request(url, headers={
                    'Authorization': 'Bearer ' + token, 'Accept': 'application/json',
                    'Accept-Language': 'nl'})
                item = {'ean': ean, 'country': country}
                try:
                    data = request_json(request, stage)
                    item.update(http_status=200, schema=schema_paths(data))
                    item['public_sample'] = {k: data[k] for k in (
                        'ean', 'id', 'title', 'offer', 'offers', 'url', 'productUrl',
                        'bolProductId', 'attributes', 'media', 'specifications') if k in data}
                    if not isinstance(data, dict) or not data:
                        raise ReviewError(stage, 'unexpected_product_schema')
                except ReviewError as exc:
                    if exc.status != 404:
                        raise
                    item.update(http_status=404, found=False)
                result['products'].append(item)
                time.sleep(1)  # At most one catalogue request/second; no token retries.
        result['status'] = 'review' if any(p['http_status'] == 200 for p in result['products']) else 'no_matches'
    except ReviewError as exc:
        result['errors'].append({'stage': exc.stage, 'reason': exc.reason, 'http_status': exc.status})
    return result


def main():
    result = review(os.environ.get('BOL_API_CLIENT_ID'), os.environ.get('BOL_API_CLIENT_SECRET'))
    output = Path('output/bol-api/review.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    # Schema details stay in the artifact; bounded safe counts are API-readable annotations.
    concise = {k: v for k, v in result.items() if k != 'products'}
    concise['products'] = [{k: v for k, v in p.items() if k not in {'schema', 'public_sample'}} for p in result['products']]
    for product in result['products']:
        if product.get('http_status') == 200:
            sample = json.dumps(product)
            if len(sample) < 25000:
                print('::notice title=Bol public product sample::' + sample.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A'), flush=True)
    message = json.dumps(concise).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print('::notice title=Bol API review::' + message, flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
            handle.write('### Bol Marketing API review\n\n```json\n' + json.dumps(result, indent=2) + '\n```\n')
    return 0 if result['status'] == 'review' else 1


if __name__ == '__main__':
    raise SystemExit(main())
