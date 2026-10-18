import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from scripts.scrapers import bestkeptrecords, dgmoutlet
from scripts.scrapers.usf.jobs import refresh_fiftiesstore_listing_prices as fifties


class PriceSourceRepairsTests(unittest.TestCase):
    def test_dgm_price_listing_never_fetches_product_details(self):
        html = '<div class="card product-box box-standard"><a class="product-name" href="/album-8719262047020">Calibro 35 LP</a><span class="product-price">24,95</span></div>'
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            scraper = dgmoutlet.DGMOutletLPScraper(str(Path(directory) / 'out.csv'), verify_detail_availability=False)
            with patch.object(scraper, '_detect_detail_availability', side_effect=AssertionError('detail request forbidden')):
                rows = scraper._parse_listing_page(html, 1, 'https://dgmoutlet.nl/lp/')
            self.assertEqual(len(rows), 1)
            self.assertIn('8719262047020', rows[0].url)

    def test_best_kept_stops_repeated_page_during_fetch_without_terminal_metadata(self):
        first = ({'product_url': 'https://bestkeptrecords.nl/product/a'},)
        second = ({'product_url': 'https://bestkeptrecords.nl/product/b'},)
        with patch.object(bestkeptrecords, 'fetch', side_effect=['first','second','repeated']) as fetch, \
             patch.object(bestkeptrecords, 'extract_last_page', return_value=None), \
             patch.object(bestkeptrecords, 'parse_listing_page', side_effect=[(list(first), None, {'a'}),(list(second), None, {'b'}),(list(second), None, {'b'})]), \
             contextlib.redirect_stdout(io.StringIO()):
            rows, pages = bestkeptrecords.scrape_listings(Mock(), 0, 0, listing_workers=1)
        self.assertEqual((len(rows), pages, fetch.call_count), (2, 2, 3))

    def test_fifties_uses_strict_storefront_category_filter_in_price_requests(self):
        response = Mock()
        response.read.return_value = b'{"product_data": [], "count": 0}'
        with patch.object(fifties, 'urlopen', return_value=response) as get:
            fifties.fetch_batch(0, 250, strict_category=True)
        payload = json.loads(parse_qs(urlsplit(get.call_args.args[0].full_url).query)['payload'][0])
        self.assertEqual(payload['filter'], 'categories in [1530]')


if __name__ == '__main__':
    unittest.main()
