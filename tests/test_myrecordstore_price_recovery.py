import contextlib
import io
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.workers.price_evidence import url_key, assess
from scripts.scrapers.usf.jobs import refresh_myrecordstore_listing_prices as source


class MyRecordStoreRecoveryTests(unittest.TestCase):
    def test_changed_genre_and_artist_keep_same_identity(self):
        old = 'https://myrecordstore.nl/item/rock/lp/doors/strange-days/4377974'
        new = 'https://www.myrecordstore.nl/item/rock-alternative/lp/the-doors/strange-days/4377974/'
        self.assertEqual(url_key(old), url_key(new))
        self.assertNotEqual(url_key(old), url_key(old.replace('4377974', '4377975')))
        self.assertNotEqual(url_key(old), url_key(old.replace('/lp/', '/cd/')))
        self.assertNotEqual(url_key(old), url_key(old.replace('myrecordstore.nl', 'example.nl')))

    def test_conflicting_prices_on_aliases_are_not_silently_chosen(self):
        records = [{'source_url': 'https://myrecordstore.nl/item/' + genre + '/lp/artist/album/4377974',
                    'price': price} for genre, price in [('rock', '20.99'), ('rock-alternative', '25.99')]]
        result = assess(records)
        self.assertEqual(result[1]['status'], 'red')
        self.assertEqual(result[0], [])

    def test_pagination_ignores_other_scopes_and_filters(self):
        html = '<a href="?tags=Voorraad&type=LP&page=20">20</a>' \
               '<a href="?type=LP&page=22525">22525</a>' \
               '<a href="/item/nieuw?type=LP&page=999">999</a>'
        self.assertEqual(source.advertised_last_page(html, source.STOCK_URL), 20)
        self.assertEqual(source.page_url(2, source.STOCK_URL), source.STOCK_URL + '&page=2')

    def test_full_run_visits_arrivals_and_stock_and_rejects_repeated_page(self):
        link = Mock(source_url='https://myrecordstore.nl/item/rock/lp/artist/album/123')
        response = Mock(text='<html>listing</html>')
        with patch.object(source.requests, 'Session') as session, \
             patch.object(source, 'parse_listing_page', return_value=([link], [])), \
             patch.object(source, 'advertised_last_page', return_value=1), \
             patch('sys.argv', ['worker', '--max-pages', '0', '--sleep', '0']), \
             contextlib.redirect_stdout(io.StringIO()):
            session.return_value.get.return_value = response
            self.assertEqual(source.main(), 0)
            self.assertEqual([x.args[0] for x in session.return_value.get.call_args_list],
                             [source.SEED_URL, source.STOCK_URL])
        with patch.object(source.requests, 'Session') as session, \
             patch.object(source, 'parse_listing_page', return_value=([link], [])), \
             patch.object(source, 'advertised_last_page', return_value=3), \
             patch('sys.argv', ['worker', '--max-pages', '0', '--sleep', '0']), \
             contextlib.redirect_stdout(io.StringIO()):
            session.return_value.get.return_value = response
            with self.assertRaisesRegex(RuntimeError, 'repeated page'):
                source.main()

    def test_empty_or_oversized_scope_cannot_succeed(self):
        for count in (1, source.MAX_CATALOGUE_PAGES + 1):
            with self.subTest(count=count), \
                 patch.object(source.requests, 'Session'), \
                 patch.object(source, 'parse_listing_page', return_value=([], [])), \
                 patch.object(source, 'advertised_last_page', return_value=count), \
                 patch('sys.argv', ['worker', '--max-pages', '0']), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    source.main()

    def test_failed_page_aborts_before_any_native_write(self):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError('429 blocked')
        with patch.object(source.requests, 'Session') as session, \
             patch.object(source, 'upsert_discovered_links') as write, \
             patch('sys.argv', ['worker', '--max-pages', '1', '--write']), \
             contextlib.redirect_stdout(io.StringIO()):
            session.return_value.get.return_value = response
            with self.assertRaises(requests.HTTPError):
                source.main()
            write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
