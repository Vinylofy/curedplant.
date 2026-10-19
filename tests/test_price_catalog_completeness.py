"""Incomplete native catalogues must never reach the price writer."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.scrapers.usf.jobs import refresh_fiftiesstore_listing_prices as fifties
from scripts.scrapers.usf.jobs import refresh_variaworld_listing_prices as varia
from scripts.workers import run_catalog_price as worker


class CatalogueCompletenessTests(unittest.TestCase):
    def response(self, status=200, body=None):
        response = requests.Response()
        response.status_code = status
        response.url = 'https://www.variaworld.nl/vinyl/lp-nieuw/1'
        response._content = (body if body is not None else
            '<div id="overzicht_container"><a class="overzichtbox_2" '
            'href="/artikel/detail.php?at=123456"><span class="koptekst">Artist</span>'
            '<span class="tekst">Album LP</span><span class="overzicht_prijs">24,95</span>'
            '</a></div>').encode()
        response.encoding = 'utf-8'
        return response

    def run_varia(self, responses):
        session = Mock()
        session.get.side_effect = responses
        with patch.object(varia.requests, 'Session', return_value=session), \
             patch.object(varia, 'SEEDS', {'lp': 'https://www.variaworld.nl/vinyl/{page}'}), \
             patch('sys.argv', ['refresh', '--max-pages', '0', '--sleep', '0']), \
             contextlib.redirect_stdout(io.StringIO()):
            result = varia.main()
        return result, session

    def batch(self, count=2, identifier=1):
        return {'count': count, 'product_data': [{
            'id': identifier, 'name': 'Artist Album LP', 'categories': [1530],
            'url': f'https://www.fiftiesstore.nl/album-{identifier}.html', 'price': 24.95}]}

    def run_fifties(self, batches, limit=0):
        with patch.object(fifties, 'fetch_batch', side_effect=batches), \
             patch('sys.argv', ['refresh', '--strict-category', '--max-products', str(limit), '--sleep', '0']), \
             contextlib.redirect_stdout(io.StringIO()):
            return fifties.main()

    def test_varia_rate_limit_after_prices_is_a_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'HTTP 429'):
            self.run_varia([self.response(), self.response(429)])

    def test_varia_server_errors_retry_same_page_then_fail(self):
        with self.assertRaisesRegex(RuntimeError, 'HTTP 503'):
            self.run_varia([self.response(), *[self.response(503) for _ in range(3)]])

    def test_varia_transport_failure_cannot_skip_a_page(self):
        with self.assertRaisesRegex(RuntimeError, 'Incomplete Variaworld'):
            self.run_varia([self.response(), *[requests.Timeout('timeout') for _ in range(3)]])

    def test_varia_recovered_server_error_does_not_advance_page(self):
        result, session = self.run_varia([
            self.response(503), self.response(), *[self.response(body='') for _ in range(3)]])
        self.assertEqual(result, 0)
        urls = [call.args[0] for call in session.get.call_args_list]
        self.assertEqual(urls[:2], ['https://www.variaworld.nl/vinyl/1'] * 2)
        self.assertTrue(all(url.endswith('/2') for url in urls[2:]))

    def test_varia_failed_empty_page_retry_is_not_terminal(self):
        for failure in [self.response(429), self.response(503), requests.Timeout('timeout')]:
            with self.subTest(failure=failure), self.assertRaises((requests.RequestException, RuntimeError)):
                self.run_varia([self.response(), self.response(body=''), failure])

    def test_varia_block_html_is_not_catalogue_end(self):
        with self.assertRaisesRegex(RuntimeError, 'blocked listing'):
            self.run_varia([self.response(), *[self.response(body='Access denied captcha') for _ in range(3)]])

    def test_varia_normal_empty_page_with_robots_metadata_is_terminal(self):
        empty = '<html><head><meta name="robots" content="index,follow"></head><body>Geen artikelen</body></html>'
        result, _ = self.run_varia([self.response(), *[self.response(body=empty) for _ in range(3)]])
        self.assertEqual(result, 0)

    def test_fifties_empty_batch_before_reported_total_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'empty batch at 1 of 2'):
            self.run_fifties([self.batch(), {'count': 2, 'product_data': []}])

    def test_fifties_repeated_product_cannot_fake_completeness(self):
        with self.assertRaisesRegex(RuntimeError, 'repeated product'):
            self.run_fifties([self.batch(), self.batch()])

    def test_fifties_missing_array_and_changed_count_fail(self):
        for second in [{'count': 2}, self.batch(count=3, identifier=2)]:
            with self.subTest(second=second), self.assertRaises(RuntimeError):
                self.run_fifties([self.batch(), second])

    def test_fifties_full_catalogue_and_explicit_pilot_still_pass(self):
        self.assertEqual(self.run_fifties([self.batch(), self.batch(identifier=2)]), 0)
        self.assertEqual(self.run_fifties([self.batch(count=100)], limit=1), 0)

    def test_fifties_product_without_url_fails(self):
        batch = self.batch(count=1)
        batch['product_data'][0].pop('url')
        with self.assertRaisesRegex(RuntimeError, 'without a URL'):
            self.run_fifties([batch])

    def test_fifties_bounded_native_write_cannot_delist_missing_products(self):
        with patch('sys.argv', ['refresh', '--write', '--max-products', '1']), \
             contextlib.redirect_stderr(io.StringIO()), \
             patch.object(fifties, 'fetch_batch') as fetch, self.assertRaises(SystemExit):
            fifties.main()
        fetch.assert_not_called()

    def test_incomplete_sources_make_write_worker_red_without_database_writes(self):
        for shop in ['variaworld', 'fiftiesstore']:
            with self.subTest(shop=shop), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                def native(command, **kwargs):
                    with patch.dict(os.environ, kwargs['env']):
                        try:
                            if shop == 'variaworld':
                                self.run_varia([self.response(), self.response(429)])
                            else:
                                self.run_fifties([self.batch(), {'count': 2, 'product_data': []}])
                        except (RuntimeError, requests.RequestException):
                            return Mock(returncode=1)
                    return Mock(returncode=0)
                with patch.object(worker, 'Path', side_effect=lambda path: root / path), \
                     patch('sys.argv', ['worker', '--worker', shop, '--limit', '0', '--write']), \
                     patch.object(worker.subprocess, 'run', side_effect=native), \
                     patch('scripts.workers.price_database.update_existing') as writer, \
                     contextlib.redirect_stdout(io.StringIO()):
                    result = worker.main()
                summary = json.loads((root / 'output/price-verification' / shop / 'summary.json').read_text())
                self.assertEqual(result, 1)
                self.assertEqual(summary['status'], 'red')
                self.assertEqual(summary['database_writes'], 0)
                self.assertEqual(summary['priced_products'], 1)
                writer.assert_not_called()
