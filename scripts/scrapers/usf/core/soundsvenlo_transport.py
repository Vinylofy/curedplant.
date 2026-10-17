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
