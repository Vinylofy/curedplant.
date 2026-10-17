"""Ordinary browser rendering for three shops whose HTTP frontend needs it."""
from urllib.parse import urlparse

import requests

BROWSER_HOSTS = {
    'www.cdhal.nl', 'cdhal.nl', 'northendhaarlem.nl',
    'www.northendhaarlem.nl', 'sounds-venlo.nl', 'www.sounds-venlo.nl',
}


def get_with_browser(session, url, **kwargs):
    response = session.get(url, **kwargs)
    if response.status_code != 403 or urlparse(url).hostname not in BROWSER_HOSTS:
        return response
    # One ordinary browser navigation; never solve challenges or retry a block.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale='nl-NL')
            documents = []
            page.on('response', lambda r: documents.append(r)
                    if r.request.resource_type == 'document' and r.frame == page.main_frame else None)
            observed = page.goto(url, wait_until='domcontentloaded', timeout=45000)
            if observed is None:
                raise requests.HTTPError(f'Browser returned no HTTP response: {url}')
            if observed.status == 403:
                # A normal page may still be running its own scripts. Allow one
                # bounded render interval; no stealth, CAPTCHA solver or IP retry.
                page.wait_for_timeout(8000)
                if documents:
                    observed = documents[-1]
            result = requests.Response()
            result.status_code = observed.status
            # Do not persist temporary challenge query parameters in artifacts.
            parsed = urlparse(page.url)
            result.url = parsed._replace(query='', fragment='').geturl()
            result.encoding = 'utf-8'
            result._content = page.content().encode('utf-8')
            result.headers.update(observed.headers)
            print(f'[BROWSER-TRANSPORT] status={result.status_code} url={result.url}', flush=True)
            return result
        finally:
            browser.close()
