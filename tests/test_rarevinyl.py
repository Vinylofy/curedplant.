import unittest
from unittest.mock import Mock, patch
from scripts.scrapers.rarevinyl import listing, enrich, valid_gtin, fetch

def product(**changes):
    result = {'id': 123, 'handle': 'artist-album-lp', 'title': 'Artist Album - Sealed Vinyl LP',
              'vendor': 'Artist', 'tags': ['Sealed', 'WHOLESALENEW'],
              'variants': [{'id': 77, 'price': '19.99', 'compare_at_price': '24.99', 'available': True}], 'images': []}
    result.update(changes)
    return result

class RareVinylTests(unittest.TestCase):
    def test_sale_and_identity(self):
        row = listing(product())
        self.assertEqual((row['price'], row['compare_at_price'], row['album_raw']), ('19.99', '24.99', 'Album - Sealed Vinyl LP'))
        self.assertEqual(row['condition_status'], 'unknown')
        self.assertTrue(row['publication_blocked'])

    def test_barcode_check_digit(self):
        self.assertEqual(valid_gtin('0602508046131'), '0602508046131')
        self.assertIsNone(valid_gtin('0602508046132'))
        self.assertIsNone(valid_gtin('barcode:0602508046131'))

    def test_cd_and_no_ean(self):
        row = listing(product(title='Artist Album CD', tags=['CD', 'Sealed']))
        self.assertEqual(row['format_status'], 'other_or_unknown')
        self.assertIsNone(row['barcode'])
        self.assertIsNotNone(row['album_raw'])

    def test_detail_must_match_product_variant_and_price(self):
        row = listing(product())
        detail = {'id': 123, 'variants': [{'id': 77, 'price': 1999, 'barcode': '0602508046131'}]}
        self.assertEqual(enrich(row, detail)['barcode'], '0602508046131')
        for changed in ({'id': 124, 'variants': detail['variants']}, {'id': 123, 'variants': [{'id': 77, 'price': 999}]}):
            with self.assertRaises(ValueError): enrich(row, changed)

    def test_multiple_variants_and_foreign_handle_rejected(self):
        with self.assertRaises(ValueError): listing(product(handle='../unsafe'))
        with self.assertRaises(ValueError): listing(product(variants=[{}, {}]))

    @patch('scripts.scrapers.rarevinyl.time.sleep')
    def test_retry_and_429_stop(self, sleep):
        session = Mock()
        bad, good = Mock(status_code=503), Mock(status_code=200, is_redirect=False)
        good.json.return_value = {'ok': True}
        session.get.side_effect = [bad, good]
        self.assertEqual(fetch(session, Mock(can_fetch=Mock(return_value=True)), 'https://eu.rarevinyl.com/products/example.js'), {'ok': True})
        self.assertEqual(session.get.call_count, 2)
        session.get.reset_mock(side_effect=True)
        session.get.return_value = Mock(status_code=429)
        with self.assertRaises(RuntimeError): fetch(session, Mock(can_fetch=Mock(return_value=True)), 'https://eu.rarevinyl.com/products/example.js')
        self.assertEqual(session.get.call_count, 1)

if __name__ == '__main__': unittest.main()
