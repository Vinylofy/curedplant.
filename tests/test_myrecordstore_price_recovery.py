import contextlib
import io
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
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

    def test_target_search_only_accepts_registered_article_not_neighbor(self):
        html = '<main>' + ''.join(
            '<div><p>Artist - <a href="/item/rock/lp/artist/album/' + article + '">Album</a></p>'
            '<p class="bg-(--secondary)">24,99</p><p>Op voorraad</p></div>'
            for article in ('8518501', '6359001')) + '</main>'
        links, offers = source.parse_listing_page(html, listing_url=source.STOCK_URL,
            page=1, seen_at=datetime.now(timezone.utc), wanted_ids={'8518501'})
        self.assertEqual([x.source_product_id for x in links], ['8518501'])
        self.assertEqual([x.price for x in offers], ['24.99'])

    def test_existing_offer_fallback_uses_barcode_and_exact_shop_id(self):
        listed = Mock(source_url='https://myrecordstore.nl/item/rock/lp/artist/album/123')
        recovered = Mock(source_url='https://myrecordstore.nl/item/rock-alternative/lp/artist/album/8518501')
        target = {'source_url': 'https://myrecordstore.nl/item/rock/lp/artist/album/8518501',
                  'source_product_id': '8518501', 'ean': '0810020501780'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'known.json'
            path.write_text(json.dumps([target]))
            with patch.object(source.requests, 'Session') as session, \
                 patch.object(source.time, 'sleep'), \
                 patch.object(source, 'parse_listing_page', side_effect=[([listed], []), ([listed], []), ([recovered], [])]) as parser, \
                 patch.object(source, 'advertised_last_page', return_value=1), \
                 patch('sys.argv', ['worker', '--max-pages', '0', '--existing-offers-file', str(path)]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(source.main(), 0)
                self.assertEqual(session.return_value.get.call_args.args[0],
                    'https://myrecordstore.nl/item/search?q=0810020501780&type=LP')
                self.assertEqual(parser.call_args.kwargs['wanted_ids'], {'8518501'})

    def test_full_worker_exports_known_offers_without_passing_db_credentials(self):
        from scripts.workers import run_catalog_price as worker
        from scripts.workers.price_evidence import capture
        target = {'source_url': 'https://myrecordstore.nl/item/rock/lp/artist/album/8518501',
                  'source_product_id': '8518501', 'ean': '0810020501780'}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(worker, 'Path', side_effect=lambda path: Path(directory) / path), \
             patch('scripts.workers.myrecordstore_targets.registered_offers', return_value=[target]), \
             patch('scripts.workers.price_database.update_existing') as writer, \
             patch.dict(os.environ, {'DATABASE_URL': 'must-stay-in-parent'}), \
             patch('sys.argv', ['worker', '--worker', 'myrecordstore', '--limit', '0']), \
             contextlib.redirect_stdout(io.StringIO()):
            def collect(command, **kwargs):
                self.assertEqual(kwargs['env']['DATABASE_URL'], '')
                self.assertNotIn('--write', command)
                path = command[command.index('--existing-offers-file') + 1]
                self.assertEqual(json.loads(Path(path).read_text()), [target])
                with patch.dict(os.environ, kwargs['env']):
                    capture({'source_url': target['source_url'], 'price': '24.99'})
                return Mock(returncode=0)
            with patch.object(worker.subprocess, 'run', side_effect=collect):
                self.assertEqual(worker.main(), 0)
            writer.assert_not_called()

    def test_failed_page_aborts_before_any_native_write(self):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError('429 blocked')
        with patch.object(source.requests, 'Session') as session, \
             patch.object(source, 'upsert_discovered_links') as write, \
             patch.object(source.time, 'sleep'), \
             patch('sys.argv', ['worker', '--max-pages', '1', '--write']), \
             contextlib.redirect_stdout(io.StringIO()):
            session.return_value.get.return_value = response
            with self.assertRaises(requests.HTTPError):
                source.main()
            write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
