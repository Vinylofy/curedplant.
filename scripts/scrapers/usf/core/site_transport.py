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
            observed = page.goto(url, wait_until='domcontentloaded', timeout=45000)
            if observed is None:
                raise requests.HTTPError(f'Browser returned no HTTP response: {url}')
            result = requests.Response()
            result.status_code = observed.status
            result.url = page.url
            result.encoding = 'utf-8'
            result._content = page.content().encode('utf-8')
            result.headers.update(observed.headers)
            print(f'[BROWSER-TRANSPORT] status={result.status_code} url={result.url}', flush=True)
            return result
        finally:
            browser.close()
