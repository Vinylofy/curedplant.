import json
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.workers.ean_sources import EanSource

GTIN = '00792755872161'
OTHER_GTIN = '00602478857188'


def response(body, url='https://test.invalid/products/own-record'):
    result = requests.Response()
    result.status_code, result.url = 200, url
    result._content = (json.dumps(body) if isinstance(body, (dict, list)) else body).encode()
    return result


class EanSourceTests(unittest.TestCase):
    def source(self, shop, body):
        source = EanSource(shop, sleeper=lambda _: None)
        self.addCleanup(source.close)
        source.get = Mock(return_value=response(body))
        return source

    def test_platenzaak_listing_list_contract_and_own_ean_table(self):
        html = '''<div class="product-block__inner"><div class="product-block__title-price">
        <a class="title" href="/products/own-record">Artist - Album</a>
        <div class="price"><span class="amount">€25.00</span></div></div></div>'''
        source = self.source('platenzaak', html)
        rows, cursor = source.catalog({'page': 2, 'seed': 0})
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['source_url'].endswith('/products/own-record'))
        self.assertEqual(cursor['page'], 3)
        source.get.return_value = response(f'<h1>Album</h1><div class="product-detail-accordion"><table><tr><td>EAN</td><td>{GTIN}</td></tr></table></div>')
        self.assertEqual(source.detail(rows[0])['ean'], GTIN)

    def test_bob_uses_native_product_card_selector(self):
        source = self.source('bobsvinyl', '<div class="card-wrapper product-card-wrapper"><a class="full-unstyled-link" href="/products/own-record">Artist - Album - LP</a><span class="price-item">€25.00</span></div>')
        rows, cursor = source.catalog({'page': 1, 'seed': 0})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['payload']['title'], 'Album - LP')
        self.assertEqual(cursor['page'], 2)

    def test_shopify_ambiguous_variant_codes_are_not_guessed(self):
        source = self.source('atthemovies', {'title': 'Album', 'variants': [{'id': 1, 'barcode': GTIN}, {'id': 2, 'barcode': OTHER_GTIN}]})
        row = {'source_url': 'https://test.invalid/products/own-record', 'payload': {}}
        self.assertIsNone(source.detail(row)['ean'])
        row['payload']['variant_id'] = '2'
        self.assertEqual(source.detail(row)['ean'], OTHER_GTIN)

    def test_blackvinyl_detail_and_listing_disagreement_is_rejected(self):
        source = self.source('blackvinyl', '<h1>Album</h1>')
        row = {'source_url': 'https://test.invalid/products/own-record', 'payload': {'ean': GTIN}}
        with patch('scripts.scrapers.blackvinyl.detail_ean_from_html', return_value=(OTHER_GTIN, OTHER_GTIN)):
            self.assertIsNone(source.detail(row)['ean'])
        with patch('scripts.scrapers.blackvinyl.detail_ean_from_html', return_value=None):
            self.assertEqual(source.detail(row)['ean'], GTIN)

    def test_filtered_shopify_page_is_not_end_of_catalogue(self):
        source = self.source('shop3345', {'products': [{'title': 'CD', 'handle': 'cd-record'}]})
        rows, cursor = source.catalog({'page': 1, 'seed': 0})
        self.assertEqual(rows, [])
        self.assertEqual(cursor, {'page': 2, 'seed': 0})
