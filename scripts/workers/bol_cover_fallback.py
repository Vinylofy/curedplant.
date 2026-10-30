"""NL-only Bol cover discovery. Never downloads images or publishes covers."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from urllib.request import Request

import psycopg

from scripts.importers.bol_api_review import authenticate, request_json, ReviewError, CATALOG_URL
from scripts.importers.common import strict_normalize_gtin


def gtin(value):
    # Reject damaged input before the shared normalizer strips punctuation.
    text = str(value or '').strip()
    return strict_normalize_gtin(text) if re.fullmatch(r'[0-9]{8}|[0-9]{12,14}', text) and set(text) != {'0'} else None


def medium(value):
    text = str(value or '').strip().casefold()
    vinyl = bool(re.search(r'\b(vinyl|lp|\d+x?lp)\b', text))
    cd = bool(re.search(r'\b(cd|compact disc)\b', text))
    if re.search(r'\b(dvd|blu-ray|cassette|digital|download)\b', text) or vinyl == cd:
        return None
    return 'vinyl' if vinyl else 'cd'


def attributes(data):
    """Flatten the official specificationGroups schema, preserving conflicts."""
    result = {}
    groups = data.get('specificationGroups', [])
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        specs = group.get('specifications', [])
        for item in specs if isinstance(specs, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get('name'), str):
                continue
            value = item.get('values')
            if isinstance(value, list) and len(value) == 1:
                value = value[0]
            if isinstance(value, str):
                name, value = item['name'].strip().casefold(), value.strip().casefold()
                if name in result and result[name] != value:
                    raise ValueError('conflicting_specifications')
                result[name] = value
    return result


def validate(product, data):
    result = {'source': 'bol_affiliate', 'country': 'NL', 'match_status': 'rejected',
              'error_status': None, 'external_image_url': None, 'bol_product_reference': None,
              'ean': product.get('ean'), 'verified_at': datetime.now(timezone.utc).isoformat(),
              'publication_eligible': False, 'rights_status': 'unconfirmed'}
    if any(product.get(k) for k in ('cover_url', 'cover_storage_path', 'cover_source_url')):
        result['error_status'] = 'existing_cover'
        return result
    expected = gtin(product.get('ean'))
    if not expected or (product.get('gtin_normalized') and product['gtin_normalized'] != expected):
        result['error_status'] = 'invalid_ean'
        return result
    if data is None:
        result['error_status'] = 'not_found'
        return result
    if not isinstance(data, dict) or gtin(data.get('ean')) != expected:
        result['error_status'] = 'ean_mismatch'
        return result
    result['exact_match'] = True
    if data.get('countryCode', 'NL') != 'NL':
        result['error_status'] = 'wrong_market'
        return result
    attrs = attributes(data)
    format_value = attrs.get('type uitvoering') or attrs.get('drager') or attrs.get('format')
    wanted, found = medium(product.get('format_label')), medium(format_value)
    if wanted is None or found != wanted:
        result['error_status'] = 'format_mismatch_or_unknown'
        return result
    remote_title = str(data.get('title') or '').casefold()
    title_medium = medium(remote_title)
    if title_medium and title_medium != wanted:
        result['error_status'] = 'format_mismatch_or_unknown'
        return result
    variant_pattern = r'\b(red|blue|green|clear|coloured|colored|splatter|picture disc|box set|numbered|remaster(?:ed)?|deluxe|limited|gatefold)\b'
    local_variants = set(re.findall(variant_pattern, str(product.get('title') or '').casefold()))
    remote_variants = set(re.findall(variant_pattern, remote_title))
    if local_variants != remote_variants:
        result['error_status'] = 'variant_review'
        return result
    # Compare explicit variant evidence where available. Titles never prove identity.
    for keys, local in [(('editie', 'edition'), 'edition'), (('kleur', 'color'), 'color'),
                        (('verpakking', 'packaging'), 'packaging')]:
        remote = next((attrs[k] for k in keys if attrs.get(k)), None)
        existing = product.get(local)
        if remote and (not existing or str(existing).strip().casefold() != remote):
            result['error_status'] = 'variant_review'
            return result
        if existing and not remote:
            result['error_status'] = 'variant_review'
            return result
    # A non-generic canonical format itself can contain colour/edition evidence.
    label = str(product.get('format_label') or '').strip().casefold()
    if label not in {'lp', 'vinyl', 'cd', 'compact disc'} and label != str(format_value or '').strip().casefold():
        result['error_status'] = 'variant_review'
        return result
    reference = str(data.get('id') or data.get('bolProductId') or '')
    if not re.fullmatch(r'[0-9]{5,30}', reference):
        result['error_status'] = 'missing_product_reference'
        return result
    # include-image returns the explicit main product image in the official API.
    image = data.get('image')
    images = [image] if isinstance(image, dict) else []
    urls = []
    for item in images if isinstance(images, list) else []:
        url = item.get('url')
        if not isinstance(url, str):
            continue
        parts = urlsplit(url)
        if (parts.scheme == 'https' and parts.hostname == 'media.s-bol.com'
                and parts.port in (None, 443) and not parts.username and not parts.password
                and not parts.fragment and not any(c.isspace() for c in url)):
            urls.append(url)
    if not urls:
        result['error_status'] = 'missing_image'
        return result
    result.update(match_status='exact_variant', external_image_url=urls[0],
                  bol_product_reference=reference)
    return result


class Client:
    def __init__(self, metrics, sleep=time.sleep, clock=time.monotonic):
        self.metrics, self.sleep, self.clock = metrics, sleep, clock
        self.token, self.expires, self.last = None, 0, None

    def lookup(self, code):
        normalized = gtin(code)
        if not normalized or not normalized.startswith('0'):
            raise ValueError('unsupported_ean')
        for attempt in range(3):
            if self.last is not None:
                self.sleep(max(0, 4 - (self.clock() - self.last)))
            self.last = self.clock()
            try:
                if self.clock() >= self.expires - 30:
                    self.token, lifetime = authenticate(os.environ.get('BOL_API_CLIENT_ID'),
                                                       os.environ.get('BOL_API_CLIENT_SECRET'))
                    self.expires = self.clock() + lifetime
                self.metrics['bol_lookups'] += 1
                return request_json(Request(CATALOG_URL + normalized[1:] +
                    '?country-code=NL&include-specifications=true&include-image=true',
                    headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json',
                             'Accept-Language': 'nl'}), 'cover_catalog')
            except ReviewError as exc:
                if exc.status == 404:
                    return None
                self.metrics['api_failures'] += 1
                if exc.status == 429:
                    self.metrics['rate_limits'] += 1
                    # The shared HTTP helper sanitizes headers. End this run instead
                    # of retrying before an unknown Retry-After has elapsed.
                    raise
                # Bol explicitly forbids automatic retries of HTTP 500.
                if attempt == 2 or (exc.status not in (None, 502, 503, 504)):
                    raise
                self.sleep(2 ** (attempt + 1))


def run(dsn, *, write=False, limit=100, env=None, connect=psycopg.connect, client_factory=Client):
    env = os.environ if env is None else env
    metrics = Counter({k: 0 for k in ('missing_covers', 'bol_lookups', 'exact_matches',
        'rejected_matches', 'candidates_accepted', 'candidates_registered', 'published',
        'api_failures', 'rate_limits', 'skipped_existing', 'checked', 'database_writes')})
    summary = {'status': 'disabled', 'dry_run': not write, 'metrics': metrics,
               'publication': 'blocked_pending_rights_and_publisher_support', 'errors': []}
    if env.get('BOL_COVER_FALLBACK_ENABLED', 'false') != 'true':
        return summary
    if env.get('BOL_COVER_PUBLICATION_ENABLED', 'false') != 'false':
        summary.update(status='blocked', errors=['publication_not_supported'])
        return summary
    if not 1 <= limit <= 100 or not dsn or not all(env.get(k) for k in ('BOL_API_CLIENT_ID', 'BOL_API_CLIENT_SECRET')):
        summary.update(status='blocked', errors=['missing_or_invalid_configuration'])
        return summary
    client = client_factory(metrics)
    try:
        with connect(dsn, prepare_threshold=None) as conn:
            # One queue row at a time, committed evidence is the checkpoint. A
            # crash releases locks and repeats only uncommitted work. No leases.
            if not write:
                conn.execute('set transaction read only')
            for lane, budget in [('new', (limit + 1) // 2), ('historical', limit // 2)]:
                seen = []
                for _ in range(budget):
                    row = conn.execute('select public.bol_cover_next(%s,%s,%s::uuid[])',
                                       (lane, write, seen)).fetchone()
                    product = row[0] if row else None
                    if not product:
                        break
                    seen.append(product['id'])
                    result = validate(product, None)
                    if result['error_status'] == 'existing_cover':
                        metrics['skipped_existing'] += 1
                    elif result['error_status'] == 'not_found':
                        try:
                            result = validate(product, client.lookup(product['ean']))
                        except ReviewError as exc:
                            result.update(error_status='api_failure', http_status=exc.status)
                            if write:
                                conn.execute('select public.bol_cover_record(%s,%s::jsonb)',
                                             (product['id'], json.dumps(result)))
                                conn.commit()
                                metrics['database_writes'] += 1
                            raise
                        except ValueError:
                            result.update(error_status='unsupported_ean')
                    metrics['checked'] += 1
                    metrics['exact_matches'] += int(bool(result.get('exact_match')))
                    accepted = result['match_status'] == 'exact_variant'
                    metrics['candidates_accepted'] += int(accepted)
                    metrics['rejected_matches'] += int(not accepted)
                    if write:
                        registered = conn.execute('select public.bol_cover_record(%s,%s::jsonb)',
                            (product['id'], json.dumps(result))).fetchone()[0]
                        conn.commit()
                        metrics['database_writes'] += int(registered >= 0)
                        metrics['candidates_registered'] += int(registered == 1)
                        metrics['skipped_existing'] += int(registered == -1)
                    else:
                        conn.rollback()
                        conn.execute('set transaction read only')
            counters = conn.execute('select public.bol_cover_counts()').fetchone()[0]
            metrics['missing_covers'] = counters.pop('missing_covers')
            summary['backlog'] = counters
            summary['status'] = 'success'
    except ReviewError as exc:
        summary.update(status='blocked', errors=[{'stage': exc.stage, 'reason': exc.reason, 'http_status': exc.status}])
    except (psycopg.Error, ValueError, TypeError, KeyError, OSError):
        summary.update(status='blocked', errors=['database_contract_or_response_invalid'])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    try:
        limit = int(os.environ.get('BOL_COVER_BATCH_SIZE') or '100')
    except ValueError:
        limit = 0
    summary = run(os.environ.get('BOL_COVER_DATABASE_URL', ''), write=args.write, limit=limit)
    # Counts only: no API responses, image URLs, credentials, titles or EANs.
    text = json.dumps(summary, indent=2)
    print(text)
    path = Path('output/bol-cover/summary.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + '\n', encoding='utf8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf8') as handle:
            handle.write('### Bol cover fallback\n\n```json\n' + text + '\n```\n')
    return 0 if summary['status'] in ('success', 'disabled') else 1


if __name__ == '__main__':
    raise SystemExit(main())
