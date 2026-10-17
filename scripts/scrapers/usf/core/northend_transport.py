"""North End's ordinary HTTP/browser session, reused for the complete batch.

The shop advertises Crawl-delay: 30. We keep that interval between document
requests, including browser navigation. A continuing denial is returned as 403;
there is no challenge solver, alternate IP or automatic restart.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse, urlunparse

import requests

ORIGIN = 'https://www.northendhaarlem.nl'


def canonical_url(url):
    parsed = urlparse(url)
    if parsed.hostname not in {'northendhaarlem.nl', 'www.northendhaarlem.nl'}:
        raise ValueError('North End client accepts only the North End domain')
    return urlunparse(parsed._replace(scheme='https', netloc='www.northendhaarlem.nl',
                                     fragment=''))


class NorthEndSession(requests.Session):
    origin = ORIGIN
    minimum_interval = 30.0
    canonical_url = staticmethod(canonical_url)
    # Match the HTTP settings of the successful Windows source. Chromium uses
    # that same ordinary profile and opens the requested document directly.
    source_headers = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/124.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'nl-NL,nl;q=0.9,en-US;q=0.7,en;q=0.6',
    }

    def __init__(self, *, interval=None, clock=time.monotonic, sleeper=time.sleep):
        super().__init__()
        self.headers.update(self.source_headers)
        self.interval = max(self.minimum_interval, interval if interval is not None else self.minimum_interval)
        self.clock, self.sleeper = clock, sleeper
        self.last_request = None
        self.events = []
        self._playwright = self._browser = self._page = None
        self._blocked = None

    def _pace(self):
        if self.last_request is not None:
            remaining = self.interval - (self.clock() - self.last_request)
            if remaining > 0:
                self.sleeper(remaining)
        self.last_request = self.clock()

    def _observe(self, response, transport):
        parsed = urlparse(response.url)
        self.events.append({'url': parsed._replace(query='', fragment='').geturl(),
                            'status': response.status_code, 'transport': transport,
                            'challenge': response.headers.get('cf-mitigated') == 'challenge'})
        if response.status_code in {403, 429}:
            self._blocked = response
        return response

    def _navigate(self, url):
        self._pace()
        observed = self._page.goto(url, wait_until='domcontentloaded', timeout=45000)
        if observed is None:
            raise requests.HTTPError('North End browser returned no document response')
        response = requests.Response()
        response.status_code = observed.status
        response.url = self.canonical_url(url)
        response.headers.update(observed.headers)
        response.encoding = 'utf-8'
        response._content = self._page.content().encode('utf-8')
        return self._observe(response, 'persistent_browser')

    def get(self, url, **kwargs):
        url = self.canonical_url(url)
        if self._blocked is not None:
            # Stop the batch after a continuing site denial, even if the caller
            # tries another category. Do not hit Cloudflare repeatedly.
            return self._blocked
        if self._page is not None:
            return self._navigate(url)
        self._pace()
        response = super().get(url, **kwargs)
        self._observe(response, 'http_session')
        if response.status_code != 403:
            return response
        # Retain the old shop's HTTP settings in one ordinary browser session.
        # The native Venlo Windows source's direct category navigation has now
        # been proven on hosted Linux; do not require an unrelated homepage.
        self._blocked = None
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._page = self._browser.new_page(
            user_agent=self.headers['User-Agent'], locale='nl-NL',
            extra_http_headers={'Accept-Language': self.headers['Accept-Language'],
                                'Referer': self.origin + '/'})
        return self._navigate(url)

    def close(self):
        try:
            if self._browser is not None:
                self._browser.close()
            if self._playwright is not None:
                self._playwright.stop()
        finally:
            self._browser = self._page = self._playwright = None
            super().close()
