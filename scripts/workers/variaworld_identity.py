"""Verify changed Variaworld article identities; listing prices remain authoritative."""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import requests

from scripts.importers.common import strict_normalize_gtin
from scripts.workers.price_evidence import url_key

PROOF_KIND = 'variaworld_product_metadata_v2'
CACHE_PATH = Path('state/variaworld/identities.json')


def valid_article_url(url):
    if urlsplit(url).scheme != 'https':
        return False
    key = url_key(url)
    return bool(re.fullmatch(r'variaworld\.nl/artikel/detail\.php\?at=\d+', key))


def detail_gtin(html):
    """Only the current product's carrier/EAN block, never related items."""
    soup = BeautifulSoup(html, 'html.parser')
    codes = set()
    for block in soup.select('.detail_tekst_container .detail_tekstblok'):
        container = block.find_parent(class_='detail_tekst_container')
        if re.search(r'bijna nieuw|zeer goed|gebruikt|tweedehands', container.get_text(' ', strip=True), re.I):
            return None
        text = block.get_text(' ', strip=True)
        if not re.search(r'Drager:\s*(?:lp nieuw|12.?inch nieuw)', text, re.I):
            continue
        if re.search(r'bijna nieuw|zeer goed|gebruikt|tweedehands', text, re.I):
            return None
        for code in re.findall(r'\bEAN:\s*(\d{8,14})\b', text, re.I):
            normalized = strict_normalize_gtin(code)
            if normalized:
                codes.add(normalized)
    return next(iter(codes)) if len(codes) == 1 else None


def verified_gtin(record):
    proof = record.get('identity_proof') or {}
    if (proof.get('kind') != PROOF_KIND or not valid_article_url(record.get('source_url', ''))
            or proof.get('url_key') != url_key(record['source_url'])):
        return None
    try:
        observed = datetime.fromisoformat(proof['observed_at'])
        now = datetime.now(timezone.utc)
        if not now - timedelta(days=14) <= observed <= now:
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return strict_normalize_gtin(proof.get('gtin'))


def fallback_matches(records, targets):
    """Reject ambiguous barcodes and competing live offers; no fuzzy matching."""
    by_gtin = defaultdict(list)
    for target in targets:
        code = strict_normalize_gtin(target.get('gtin_normalized') or target.get('ean'))
        if code:
            by_gtin[code].append(target)
    offers = defaultdict(list)
    for record in records:
        code = verified_gtin(record)
        if code:
            offers[code].append(record)
    direct = {url_key(row['source_url']) for row in records}
    matches = {}
    for code, candidates in offers.items():
        known = by_gtin.get(code, [])
        if len(candidates) != 1 or len(known) != 1:
            continue
        target = known[0]
        # A direct live listing for the existing article wins over a replacement.
        if url_key(target['product_url']) in direct:
            continue
        matches[str(target['product_id'])] = candidates[0]
    return matches


def enrich_identities(records, known_urls, *, budget=200, cache_path=CACHE_PATH, session=None, sleeper=time.sleep):
    if not 0 <= budget <= 2000:
        raise ValueError('Variaworld identity lookup budget must be between 0 and 2000')
    now = datetime.now(timezone.utc)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {'version': 1, 'entries': {}}
    if cache.get('version') != 1 or not isinstance(cache.get('entries'), dict):
        raise ValueError('Unsupported Variaworld identity cache')
    entries = cache['entries']
    session = session or requests.Session()
    session.headers.update({'User-Agent': 'Vinylofy Variaworld identity verification', 'Accept-Language': 'nl-NL,nl;q=0.9'})
    stats = {'lookups': 0, 'cache_hits': 0, 'verified': 0, 'pending': 0, 'missing_gtin': 0}
    known = {url_key(url) for url in known_urls}
    for row in records:
        url = row['source_url']
        if url_key(url) in known or not valid_article_url(url):
            continue
        key = url_key(url)
        entry = entries.get(key)
        valid = False
        if entry and entry.get('proof_kind') == PROOF_KIND:
            observed = datetime.fromisoformat(entry['observed_at'])
            lifetime = timedelta(days=14) if entry.get('gtin') else timedelta(hours=24)
            valid = now - lifetime <= observed <= now
        if valid:
            stats['cache_hits'] += 1
        elif stats['lookups'] < budget:
            for attempt in range(3):
                try:
                    response = session.get(url, timeout=(10, 30))
                except (requests.Timeout, requests.ConnectionError):
                    if attempt == 2:
                        raise
                    sleeper(5 * (attempt + 1))
                    continue
                if response.status_code >= 500 and attempt < 2:
                    sleeper(5 * (attempt + 1))
                    continue
                if response.status_code in (404, 410):
                    code = None
                else:
                    response.raise_for_status()
                    if url_key(response.url) != key:
                        raise ValueError('Variaworld identity lookup redirected to another article')
                    visible = BeautifulSoup(response.text, 'html.parser').get_text(' ', strip=True).lower()
                    if any(marker in visible for marker in ('verify you are human', 'access denied', 'checking your browser')):
                        raise RuntimeError('Blocked Variaworld identity page; do not cache as missing EAN')
                    code = detail_gtin(response.text)
                break
            entry = {'gtin': code, 'observed_at': now.isoformat(), 'proof_kind': PROOF_KIND}
            entries[key] = entry
            stats['lookups'] += 1
            # A failed later fetch can resume from already verified identities.
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(cache, sort_keys=True, indent=2) + '\n')
            temporary.replace(cache_path)
            sleeper(1.5)
        else:
            stats['pending'] += 1
            continue
        if entry.get('gtin'):
            row['identity_proof'] = {'kind': PROOF_KIND, 'url_key': key, 'gtin': entry['gtin'], 'observed_at': entry['observed_at']}
            stats['verified'] += 1
        else:
            stats['missing_gtin'] += 1
    return stats
