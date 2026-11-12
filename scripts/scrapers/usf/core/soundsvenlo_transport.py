"""Sounds Venlo's persistent session and published 10-second crawl interval."""
import os
from urllib.parse import urlparse, urlunparse

import requests

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
    browser_entry_home = False
    catalog_prefix = '/vinyl/'
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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.http_only = os.environ.get('SOUNDSVENLO_HTTP_ONLY') == 'true'
        if self.http_only:
            self.headers['User-Agent'] = 'Vinylofy-SoundsVenlo/1.0 (https://vinylofy.com; info@vinylofy.com)'

    def get(self, url, **kwargs):
        if not self.http_only:
            return super().get(url, **kwargs)
        url = self.canonical_url(url)
        if self._blocked is not None:
            return self._blocked
        self._pace()
        response = requests.Session.get(self, url, **kwargs)
        return self._observe(response, 'http_session')
