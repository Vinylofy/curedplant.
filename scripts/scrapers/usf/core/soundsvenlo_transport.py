"""Sounds Venlo's persistent session and published 10-second crawl interval."""
from urllib.parse import urlparse, urlunparse

from scripts.scrapers.usf.core.northend_transport import NorthEndSession


def canonical_url(url):
    parsed = urlparse(url)
    if parsed.hostname not in {'sounds-venlo.nl', 'www.sounds-venlo.nl'}:
        raise ValueError('Sounds Venlo client accepts only the Sounds Venlo domain')
    return urlunparse(parsed._replace(scheme='https', netloc='www.sounds-venlo.nl', fragment=''))


class SoundsVenloSession(NorthEndSession):
    # Reuse the tested session lifecycle, not North End's origin or site policy.
    origin = 'https://www.sounds-venlo.nl'
    minimum_interval = 10.0
    canonical_url = staticmethod(canonical_url)
    source_headers = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'no-cache', 'Pragma': 'no-cache',
        'Connection': 'keep-alive', 'Upgrade-Insecure-Requests': '1',
    }
