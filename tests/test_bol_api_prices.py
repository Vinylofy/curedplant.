import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from scripts.importers import bol_api_prices as api
from scripts.importers.bol_feed import FeedError
from scripts.importers.bol_api_review import ReviewError


class PriceTests(unittest.TestCase):
    def setUp(self):
        self.product = {'id': '00000000-0000-0000-0000-000000000001', 'ean': '0889854344115',
            'gtin_normalized': '00889854344115', 'format_label': 'LP', 'title': 'Canonical title'}
        self.offer = {'ean': '0889854344115', 'countryCode': 'NL', 'condition': 'NEW',
            'isPreOrder': False, 'price': 35.86, 'deliveryDescription': 'Op voorraad. Morgen in huis',
            'url': 'https://www.bol.com/nl/nl/p/iii/9200000078958183/'}
        self.now = datetime.now(timezone.utc)

    def normalize(self, offer=None, product=None):
        return api.normalize_offer(product or self.product, offer or self.offer, '123', self.now)

    def test_article_price_exact_and_shipping_seller_remain_unknown(self):
        offer = dict(self.offer, listPrice=99.99, shippingCost=5.95)
        result = self.normalize(offer)
        self.assertEqual(result['price'], '35.86')
        self.assertEqual(result['availability'], 'in_stock')
        self.assertEqual(result['title'], 'Canonical title')
        self.assertIsNone(result['shipping'])
        self.assertEqual(result['seller'], 'unknown')
        self.assertIn('s=123', result['product_url'])

    def test_missing_new_state_wrong_ean_country_and_currency_rejected(self):
        for changes in ({'condition': None}, {'condition': 'SECONDHAND'}, {'countryCode': 'BE'},
                        {'ean': '0602567549499'}, {'price': 0}, {'price': 'NaN'},
                        {'currency': 'USD'}, {'isPreOrder': None},
                        {'url': 'https://www.bol.com/be/nl/p/iii/9200000078958183/'},
                        {'url': 'https://attacker.example/nl/nl/p/iii/9200000078958183/'}):
            with self.subTest(changes=changes), self.assertRaises(FeedError):
                self.normalize(dict(self.offer, **changes))

    def test_non_vinyl_and_conflicting_registered_barcode_rejected(self):
        for changes in ({'format_label': 'CD'}, {'gtin_normalized': '00000000000000'}, {'ean': '0889854344114'}):
            with self.subTest(changes=changes), self.assertRaises(FeedError):
                self.normalize(product=dict(self.product, **changes))

    def test_delivery_in_weeks_is_not_in_stock_and_preorder_is_explicit(self):
        self.assertEqual(self.normalize(dict(self.offer, deliveryDescription='1 - 2 weken'))['availability'], 'unknown')
        self.assertEqual(self.normalize(dict(self.offer, isPreOrder=True))['availability'], 'preorder')

    def run_batch(self, response, write=False, client=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            client = client or Mock(token_requests=1)
            if response is not ...:
                client.best_offer.return_value = response
            with patch.object(api, 'load_targets', return_value=([self.product], False, 100)), \
                 patch.object(api, 'Client', return_value=client), \
                 patch.object(api, 'publish', return_value={'updated_offers': 1}) as publish:
                result = api.run('not-a-real-dsn', 1, write=write, site_id='123', progress=path)
            return result, publish.call_args_list, path.exists()

    def test_dry_run_makes_no_writes_or_progress_changes(self):
        result, calls, progressed = self.run_batch(self.offer)
        self.assertEqual(result['database_writes'], 0)
        self.assertEqual(calls, [])
        self.assertFalse(progressed)

    def test_write_is_existing_only_and_progress_advances_after_success(self):
        result, calls, progressed = self.run_batch(self.offer, write=True)
        self.assertEqual(result['database_writes'], 1)
        self.assertTrue(calls[0].kwargs['existing_only'])
        self.assertTrue(progressed)

    def test_not_found_does_not_block_later_batches_or_publish_false_price(self):
        result, calls, progressed = self.run_batch(None, write=True)
        self.assertEqual(result['skipped'], {'no_offer_404': 1})
        self.assertEqual(result['database_writes'], 0)
        self.assertEqual(calls, [])
        self.assertTrue(progressed)

    def test_http_failure_after_one_valid_offer_never_publishes_partial_batch(self):
        client = Mock(token_requests=1)
        client.best_offer.side_effect = [self.offer, ReviewError('best_offer', 'http_error', 429)]
        second = dict(self.product, id='00000000-0000-0000-0000-000000000002')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            with patch.object(api, 'load_targets', return_value=([self.product, second], False, 100)), \
                 patch.object(api, 'Client', return_value=client), patch.object(api, 'publish') as publish:
                result = api.run('dsn', 2, write=True, site_id='123', progress=path)
            self.assertFalse(path.exists())
        publish.assert_not_called()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['database_writes'], 0)

    def test_systemic_market_or_schema_problem_blocks_progress_and_publication(self):
        result, calls, progressed = self.run_batch(dict(self.offer, countryCode='BE'), write=True)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(calls, [])
        self.assertFalse(progressed)

    def test_existing_only_publisher_cannot_insert_a_missing_product(self):
        from scripts.importers import bol_feed
        from unittest.mock import MagicMock
        plan = {'errors': [], 'offers': [self.normalize()], 'captured_at': self.now.isoformat()}
        connection, cur = MagicMock(), MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cur
        cur.fetchone.return_value = ('NL', 'Bol')
        cur.fetchall.return_value = [('NL', 'confirmed')]
        with patch.object(bol_feed.psycopg, 'connect', return_value=connection), \
             patch.object(bol_feed, 'find_product', return_value=None), \
             patch.object(bol_feed, '_insert_product') as insert:
            with self.assertRaisesRegex(FeedError, 'existing_product_required'):
                bol_feed.publish(plan, 'dsn', {'NL': api.SHOP_ID}, approved=True, existing_only=True)
        insert.assert_not_called()

    def test_observed_multidisc_and_structured_vinyl_labels_are_supported(self):
        for label in ('LP (2)', '2XLP', '12" Vinyl', 'Vinyl | 1 12Inch Single | 180g Sky Blue Vinyl | Store Exclusive'):
            with self.subTest(label=label):
                self.assertTrue(api.is_vinyl_format(label))
        for label in ('CD', 'Vinyl brush', 'Vinyl | CD', 'Vinyl | Cleaning brush'):
            with self.subTest(label=label):
                self.assertFalse(api.is_vinyl_format(label))

    def test_client_reuses_token_and_refreshes_only_near_expiry(self):
        with patch.object(api, 'authenticate', side_effect=[('first-token', 300), ('second-token', 300)]) as auth, \
             patch.object(api, 'request_json', return_value=self.offer) as fetch, \
             patch.object(api.time, 'sleep'):
            client = api.Client()
            client.best_offer(self.product['ean'])
            client.best_offer(self.product['ean'])
            self.assertEqual(auth.call_count, 1)
            client.expires_at = 0
            client.best_offer(self.product['ean'])
            self.assertEqual(auth.call_count, 2)
            self.assertEqual(fetch.call_args.args[0].get_header('Authorization'), 'Bearer second-token')

    def test_client_does_not_retry_or_reauthenticate_on_rate_limit(self):
        with patch.object(api, 'authenticate', return_value=('token', 300)) as auth, \
             patch.object(api, 'request_json', side_effect=ReviewError('best_offer', 'http_error', 429)) as fetch:
            with self.assertRaises(ReviewError):
                api.Client().best_offer(self.product['ean'])
        self.assertEqual(auth.call_count, 1)
        self.assertEqual(fetch.call_count, 1)
