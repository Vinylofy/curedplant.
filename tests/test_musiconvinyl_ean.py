import json
import unittest
from unittest.mock import Mock
import requests

from scripts.scrapers.musiconvinyl import extract_detail_metadata_from_html
from scripts.workers.ean_sources import EanSource
from test_ean_sources import response, GTIN, OTHER_GTIN


class MusicOnVinylEanTests(unittest.TestCase):
    def source(self, body):
        source = EanSource('musiconvinyl', sleeper=lambda _: None)
        self.addCleanup(source.close)
        source.get = Mock(return_value=response(body, 'https://www.musiconvinyl.com/products/own'))
        return source

    def test_visible_multiline_barcode_uses_real_whitespace_and_checkdigit(self):
        html = f'<div class="product__info-container"><ul><li><strong>Barcode (EAN)</strong>:\n {GTIN}</li></ul></div>'
        result = extract_detail_metadata_from_html(html)
        self.assertEqual(result['ean'], GTIN)
        self.assertEqual(result['ean_source'], 'details_barcode_ean')
        invalid = html.replace(GTIN, GTIN[:-1] + str((int(GTIN[-1]) + 1) % 10))
        self.assertIsNone(extract_detail_metadata_from_html(invalid).get('ean'))

    def test_unrelated_jsonld_and_related_card_cannot_supply_barcode(self):
        html = ('<div class="product__info-container"><h1>Own album</h1></div>'
                f'<aside>Barcode (EAN): {GTIN}</aside>'
                '<script type="application/ld+json">' + json.dumps({
                    '@type': 'Product', 'url': 'https://www.musiconvinyl.com/products/other',
                    'gtin14': OTHER_GTIN}) + '</script>')
        self.assertIsNone(extract_detail_metadata_from_html(html, 'https://www.musiconvinyl.com/products/own').get('ean'))

    def test_conflicting_own_jsonld_and_specification_is_rejected(self):
        html = f'<main>Barcode (EAN): {GTIN}</main><script type="application/ld+json">' + json.dumps({
            '@type': 'Product', 'gtin14': OTHER_GTIN}) + '</script>'
        parsed = extract_detail_metadata_from_html(html)
        self.assertIsNone(parsed.get('ean'))
        self.assertEqual(parsed['ean_source'], 'conflicting_product_gtins')

    def test_plain_sku_or_organisation_is_not_a_gtin(self):
        for data in [{'@type': 'Product', 'sku': GTIN}, {'@type': 'Organization', 'gtin14': GTIN}]:
            self.assertIsNone(extract_detail_metadata_from_html(
                '<script type="application/ld+json">' + json.dumps(data) + '</script>').get('ean'))

    def test_catalogue_supplies_only_new_vinyl_and_preserves_artist_variant(self):
        product = {'id': 1, 'handle': 'own', 'title': 'Album', 'vendor': 'Artist',
                   'product_type': 'Vinyl', 'tags': [], 'variants': [
                       {'id': 2, 'barcode': GTIN, 'price': '25.99', 'available': True}]}
        source = self.source({'products': [product, {**product, 'handle': 'cd', 'product_type': 'CD'},
                                          {**product, 'handle': 'used', 'tags': ['used']}]})
        rows, cursor = source.catalog({'page': 1, 'seed': 0})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['payload']['format'], 'Vinyl')
        self.assertEqual(rows[0]['payload']['artist'], 'Artist')
        self.assertEqual(cursor['page'], 2)
        self.assertEqual(source.catalog(cursor)[1].get('exhausted'), True)
        source.get.assert_called_with('https://www.musiconvinyl.com/products.json?limit=100&page=2')

    def test_cd_only_page_does_not_finish_catalogue(self):
        source = self.source({'products': [{'product_type': 'CD'}]})
        rows, cursor = source.catalog({'page': 2, 'seed': 0})
        self.assertEqual(rows, [])
        self.assertEqual(cursor['page'], 3)
        self.assertNotIn('exhausted', cursor)

    def test_detail_has_no_price_and_preserves_artist(self):
        source = self.source(f'<div class="product__info-container">Barcode (EAN): {GTIN}</div>')
        row = {'source_url': 'https://www.musiconvinyl.com/products/own',
               'payload': {'title': 'Album', 'artist': 'Artist', 'product_type': 'Vinyl'}}
        result = source.detail(row)
        self.assertEqual(result['ean'], GTIN)
        self.assertEqual(result['artist'], 'Artist')
        self.assertNotIn('price', result)
        self.assertNotIn('availability', result)
        row['payload']['ean'] = OTHER_GTIN
        self.assertIsNone(source.detail(row)['ean'])

    def test_legacy_cd_queue_row_is_not_published(self):
        source = self.source(f'<main>Barcode (EAN): {GTIN}</main>')
        result = source.detail({'source_url': 'https://www.musiconvinyl.com/products/own',
                                'payload': {'title': 'Album CD', 'product_type': 'CD'}})
        self.assertIsNone(result['ean'])
        self.assertEqual(result['excluded_reason'], 'format_not_proven_vinyl')

    def fallback_source(self, data, status=404):
        source = self.source('')
        missing = response('not found'); missing.status_code = status
        source.get.side_effect = [requests.HTTPError(response=missing), response(data)]
        row = {'source_url': 'https://www.musiconvinyl.com/products/own', 'payload': {
            'product_type': 'Vinyl', 'shopify_product_id': '123', 'shopify_variant_id': '456'}}
        return source, row

    def test_runner_html_404_can_use_matching_public_product_json(self):
        source, row = self.fallback_source({'id': 123, 'title': 'Album', 'type': 'Vinyl',
                                           'vendor': 'Artist', 'variants': [{'id': 456, 'barcode': GTIN}]})
        result = source.detail(row)
        self.assertEqual(result['ean'], GTIN)
        self.assertEqual(result['ean_source'], 'shopify_product_js')
        self.assertEqual(result['html_http_status'], 404)
        self.assertNotIn('unavailable', result)
        self.assertNotIn('price', result)
        source.get.assert_called_with(row['source_url'] + '.js')

    def test_json_fallback_rejects_wrong_product_or_variant(self):
        for data in [{'id': 999}, {'id': 123, 'type': 'Vinyl', 'variants': [{'id': 999, 'barcode': GTIN}]}]:
            source, row = self.fallback_source(data)
            with self.assertRaises(ValueError):
                source.detail(row)

    def test_json_fallback_never_attempted_after_access_denial(self):
        for status in [403, 429]:
            source, row = self.fallback_source({}, status=status)
            with self.assertRaises(requests.HTTPError):
                source.detail(row)
            self.assertEqual(source.get.call_count, 1)

    def test_second_404_is_technical_error_not_confirmed_removal(self):
        source, row = self.fallback_source({})
        missing = response('not found'); missing.status_code = 404
        source.get.side_effect = [requests.HTTPError(response=missing), requests.HTTPError(response=missing)]
        with self.assertRaises(requests.HTTPError):
            source.detail(row)


if __name__ == '__main__':
    unittest.main()
