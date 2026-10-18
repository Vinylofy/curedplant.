"""Regression cases from failed scheduled runs of 18 October 2026."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
import requests

from scripts.scrapers.usf.jobs.detail_imusic import extract_title_artist
from scripts.workers.ean_sources import EanSource
from scripts.workers.ean_queue import EanQueue
from scripts.workers import run_daily_ean as daily
from tests.test_daily_ean import Progress, Queue, Source
from tests.test_ean_sources import response

GTIN = '05060854800732'


def http_error(status):
    r = response('<h1>Product not found</h1>', 'https://test.invalid/missing')
    r.status_code = status
    return requests.HTTPError(f'HTTP {status}', response=r)


class SourceRepairTests(unittest.TestCase):
    def source(self, shop, html):
        s = EanSource(shop, sleeper=lambda _: None)
        self.addCleanup(s.close)
        s.get = Mock(return_value=response(html))
        return s

    def test_bob_removed_product_is_separate_from_transport_error(self):
        s = self.source('bobsvinyl', '')
        s.get.side_effect = http_error(404)
        result = s.detail({'source_url': 'https://bobsvinyl.nl/en/products/dolly-dots-take-six-lp-e70'})
        self.assertTrue(result['unavailable'])
        self.assertEqual(result['http_status'], 404)
        self.assertIsNone(result['ean'])

    def test_cdhal_gone_does_not_hide_access_or_server_failures(self):
        s = self.source('cdhal', '')
        for status in (404, 410):
            s.get.side_effect = http_error(status)
            self.assertTrue(s.detail({'source_url': 'https://www.cdhal.nl/weezer-black-album-lp'})['unavailable'])
        for status in (403, 429, 500):
            s.get.side_effect = http_error(status)
            with self.assertRaises(requests.HTTPError):
                s.detail({'source_url': 'https://www.cdhal.nl/weezer-black-album-lp'})

    def test_other_shop_404_is_not_silently_accepted(self):
        s = self.source('colouredvinyl', '')
        s.get.side_effect = http_error(404)
        with self.assertRaises(requests.HTTPError):
            s.detail({'source_url': 'https://test.invalid/missing'})

    def test_fifties_hyva_td_and_div_specs_work_without_queue_ean(self):
        for row in ('<table><tr><td>EAN:</td><td>5060854800732</td></tr></table>',
                    '<div class="flex"><div class="font-bold">EAN</div><div>5060854800732</div></div>'):
            s = self.source('fiftiesstore', '<div class="product-info-main"><h1>Focus – Focus12 LP Nederpop</h1>'+row+'</div>')
            result = s.detail({'source_url': 'https://www.fiftiesstore.nl/focus-focus12-lp.html', 'payload': {}})
            self.assertEqual(result['ean'], GTIN)

    def test_fifties_does_not_take_related_ean_or_guess_conflicting_codes(self):
        s = self.source('fiftiesstore', '<div class="product-info-main"><h1>Focus LP</h1></div><div class="related"><table><tr><td>EAN</td><td>5060854800732</td></tr></table></div>')
        row = {'source_url': 'https://www.fiftiesstore.nl/focus-focus12-lp.html', 'payload': {}}
        self.assertIsNone(s.detail(row)['ean'])
        s.get.return_value = response('<div class="product-info-main"><h1>Focus LP</h1><table><tr><td>EAN</td><td>5060854800732</td></tr></table></div>')
        row['payload']['ean'] = '0792755872161'
        self.assertIsNone(s.detail(row)['ean'])

    def test_fifties_poster_is_not_published_as_vinyl(self):
        s = self.source('fiftiesstore', '<div class="product-info-main"><h1>U2 The Joshua Tree Tour Announcement Poster 1987</h1><table><tr><td>EAN</td><td>5060854800732</td></tr></table></div>')
        row = {'source_url': 'https://www.fiftiesstore.nl/poster.html'}
        result = s.detail(row)
        self.assertEqual(result['excluded_reason'], 'non_vinyl_poster')
        self.assertIsNone(result['ean'])
        s.get.return_value = response('<div class="product-info-main"><h1>Poster Girl LP</h1><table><tr><td>EAN</td><td>5060854800732</td></tr></table></div>')
        self.assertEqual(s.detail(row)['ean'], GTIN)

    def test_imusic_self_titled_album_uses_primary_artist_heading(self):
        html = '''<meta property="og:title" content="Love (LP) [Rocktober 2026 Red Vinyl edition] (2026)">
        <h1><div class="artist h2"><a href="/artist/Love">Love</a></div>Love</h1>
        <h2 class="artist"><a href="/artist/Love">Love</a></h2>
        <div class="related"><a href="/artist/Wrong">Wrong</a></div>'''
        title, artist = extract_title_artist(BeautifulSoup(html, 'html.parser'), [])
        self.assertEqual(artist, 'Love')
        self.assertIn('Love (LP)', title)

    def test_imusic_unrelated_artist_links_are_not_guessed(self):
        html = '<meta property="og:title" content="Unattributed album (LP)"><div class="related"><h2 class="artist"><a href="/artist/Wrong">Wrong</a></h2></div>'
        _, artist = extract_title_artist(BeautifulSoup(html, 'html.parser'), [])
        self.assertIsNone(artist)


class RemovedQueueRunTests(unittest.TestCase):
    def test_three_removed_products_do_not_abort_next_valid_detail(self):
        class RemovedThenValid(Source):
            def detail(self, row):
                if int(row['id']) < 3:
                    return {'ean': None, 'unavailable': True, 'http_status': 404}
                return super().detail(row)
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(io.StringIO()), \
                patch.object(daily, 'Path', side_effect=lambda p: Path(root)/p):
            q = Queue(4)
            result = daily.execute('bobsvinyl', 4, True, progress=Progress('bobsvinyl'), queue=q, source_factory=RemovedThenValid)
            self.assertEqual(result['attempted'], 4)
            self.assertEqual(result['unavailable'], 3)
            self.assertEqual(result['valid_eans'], 1)
            self.assertEqual(result['technical_errors'], 0)
            self.assertEqual(result['missing_ean'], 0)
            self.assertEqual(result['status'], 'green')
            self.assertEqual(len(q.done), 4)

    def test_all_removed_products_still_require_source_review(self):
        class Gone(Source):
            def detail(self, row): return {'ean': None, 'unavailable': True}
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(io.StringIO()), \
                patch.object(daily, 'Path', side_effect=lambda p: Path(root)/p):
            result = daily.execute('cdhal', 4, False, progress=Progress('cdhal'), queue=Queue(4), source_factory=Gone)
            self.assertEqual(result['unavailable'], 4)
            self.assertEqual(result['status'], 'red')


class MetadataRepairTests(unittest.TestCase):
    def test_missing_artist_preserves_ean_and_skips_canonical_upsert(self):
        conn = Mock()
        conn.cursor.return_value.__enter__ = Mock(return_value=Mock())
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        @contextlib.contextmanager
        def connection(): yield conn
        result = {'ean': '00603497810826', 'title': 'Love (LP)', 'domain': 'imusic.nl'}
        with patch('scripts.workers.ean_queue.db_connection', connection), patch('scripts.workers.ean_queue.upsert_product') as upsert:
            EanQueue().finish('imusic', {'id': 'id', 'source_url': 'https://imusic.nl/music/0603497810826', 'payload': {}}, result)
        upsert.assert_not_called()
        self.assertEqual(result['metadata_deferred'], 'missing_artist')
        self.assertEqual(result['ean'], '00603497810826')
