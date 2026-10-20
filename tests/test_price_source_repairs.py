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
from scripts.scrapers.usf.jobs import refresh_soundshaarlem_listing_prices as haarlem


class PriceSourceRepairsTests(unittest.TestCase):
    def test_fifties_broad_source_accepts_vinyl_outside_parent_category(self):
        for title in ['Artist Album LP', 'Elvis - Album 2LP', 'Artist 2-LP + CD',
                      'Artist (Gekleurd Vinyl + Poster) LP', 'Single 7" Artist', 'Artist 12-inch',
                      'Neil Sedaka Calendar Girl LP']:
            with self.subTest(title=title):
                self.assertIsNone(fifties.vinyl_exclusion_reason({'name': title, 'categories': [2012]}))
        for title in ['Artist Album CD', 'Vinyl Klok Danny Vera', 'Calendar LP Sized',
                      'Artist T-shirt Vinyl', 'Artist LP Tweedehands', 'Artist Poster']:
            with self.subTest(title=title):
                self.assertIsNotNone(fifties.vinyl_exclusion_reason({'name': title}))

    def test_fifties_price_command_uses_broad_vinyl_selection_without_delisting(self):
        from scripts.workers.run_catalog_price import command_for
        command = command_for('fiftiesstore', 0)
        self.assertIn('--vinyl-only', command)
        self.assertIn('--skip-delist-missing', command)
        self.assertNotIn('--strict-category', command)

    def test_fifties_vinyl_selection_keeps_pagination_in_source_offsets(self):
        vinyl = {'id': 2, 'name': 'Artist Album 2LP', 'categories': [2012],
                 'url': 'https://www.fiftiesstore.nl/album.html', 'price': 24.95}
        batches = [{'count': 2, 'product_data': [dict(vinyl, id=1, name='Vinyl Klok', url='https://www.fiftiesstore.nl/clock.html')]},
                   {'count': 2, 'product_data': [vinyl]}]
        with patch.object(fifties, 'fetch_batch', side_effect=batches) as fetch, \
             patch.object(fifties, 'DiscoveredLink') as link, \
             patch('sys.argv', ['refresh', '--vinyl-only', '--sleep', '0']), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fifties.main(), 0)
        self.assertEqual([c.args[0] for c in fetch.call_args_list], [0, 1])
        self.assertEqual(link.call_count, 1)
        self.assertEqual(link.call_args.kwargs['source_url'], vinyl['url'])

    def test_sounds_haarlem_preserves_thousands_and_current_sale_amount(self):
        for token in ['1,039.99', '1.039,99', '1039.99', '1039,99']:
            self.assertEqual(haarlem.extract_price('Regular price €' + token), '1039.99')
        self.assertEqual(haarlem.extract_prices('Regular price €1,299.99 Sale price €1,039.99'), ('1039.99','1299.99'))
        self.assertEqual(haarlem.extract_price('Regular price €34.99 Sale price €24.99'), '24.99')

    def test_sounds_haarlem_does_not_treat_lp_sized_calendar_as_vinyl(self):
        title='Marvel Calendar Avengers 2024 Calendar LP Sized 16 Month Calendar Ketting'
        self.assertFalse(haarlem.is_vinyl_product(title,title))
        self.assertTrue(haarlem.is_vinyl_product('Neil Sedaka Calendar Girl LP', 'Vinyl'))
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
