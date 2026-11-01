from pathlib import Path
import unittest
from unittest.mock import Mock

from scripts.scrapers.atubehighfidelity import catalogue, load_more_config, parse_detail, parse_listing, run
from scripts.scrapers.atubehighfidelity import stamp
from scripts.workers.album_offer_sources import verify_source

FIXTURES = Path(__file__).parent / 'fixtures/atubehighfidelity'
LISTING = (FIXTURES / 'listing.html').read_text()
DETAIL = (FIXTURES / 'detail-doe-maar.html').read_text()
AT = '2026-11-01T16:00:00+00:00'


class AtubePilot(unittest.TestCase):
    def setUp(self):
        self.rows = parse_listing(LISTING, AT)
        self.doe = next(r for r in self.rows if r['source_product_id'] == '64226')

    def test_sale_price_is_article_price_not_old_price_or_shipping(self):
        rows = parse_listing(LISTING + '<footer>Gratis verzending boven €150</footer>', AT)
        row = next(r for r in rows if r['source_product_id'] == '64226')
        self.assertEqual(row['price'], '34.50')
        self.assertEqual(row['ean_status'], 'EAN_NOT_CHECKED')
        self.assertEqual(row['availability'], 'unknown')

    def test_cd_and_unpriced_records_are_retained_for_review(self):
        self.assertEqual(len(self.rows), 24)
        cds = [r for r in self.rows if r['format_status'] == 'non_vinyl']
        self.assertTrue(cds)
        self.assertTrue(all('non_vinyl_or_unproven' in r['review_reasons'] for r in cds))
        self.assertTrue(any(r['price'] is None and r['review_reasons'] for r in self.rows))

    def test_own_detail_finds_explicit_ean_and_does_not_replace_listing_price(self):
        r = parse_detail(DETAIL, self.doe, AT)
        self.assertEqual((r['ean_raw'], r['route']), ('0602455508508', 'EAN'))
        self.assertEqual(r['price'], '34.50')
        self.assertEqual(r['availability'], 'in_stock')
        self.assertEqual(r['status'], 'validated')

    def test_no_ean_uses_album_route_not_numeric_article_number(self):
        body = DETAIL.replace('<th class="col label" scope="row">EAN</th>', '<th class="col label" scope="row">Other</th>')
        r = parse_detail(body, self.doe, AT)
        self.assertEqual((r['ean_raw'], r['route']), (None, 'ARTIST_TITLE'))
        self.assertEqual(r['condition_status'], 'new')

    def test_invalid_barcode_and_title_conflict_require_review(self):
        for body in [DETAIL.replace('0602455508508', '0602455508509'), DETAIL.replace('product_title">Doe Maar', 'product_title">Other Artist')]:
            with self.assertRaises(ValueError):
                parse_detail(body, self.doe, AT)

    def test_price_conflict_is_never_silently_overwritten(self):
        with self.assertRaisesRegex(ValueError, 'price_conflict'):
            parse_detail(DETAIL.replace('34,50', '39,99'), self.doe, AT)
        with self.assertRaisesRegex(ValueError, 'price_conflict'):
            parse_listing(LISTING.replace('data-price="34.5"', 'data-price="99"'), AT)

    def test_canonical_product_and_stock_identity(self):
        with self.assertRaisesRegex(ValueError, 'canonical_mismatch'):
            parse_detail(DETAIL.replace('/product/doe-maar-de-beste-2lp/', '/product/unrelated/'), self.doe, AT)
        self.assertEqual(parse_detail(DETAIL.replace('product instock', 'product outofstock'), self.doe, AT)['availability'], 'out_of_stock')

    def test_signed_variant_uses_explicit_option_not_lowest_price(self):
        row = next(r for r in self.rows if r['source_product_id'] == '84727')
        body = (FIXTURES / 'detail-anette.html').read_text()
        detail = parse_detail(body, row, AT)
        self.assertEqual(detail['price'], '87.00')
        self.assertEqual(detail['selected_variant']['variation_id'], 98254)
        self.assertIn('attribute_keuze=Gesigneerd', detail['offer_url'])
        self.assertEqual(detail['route'], 'ARTIST_TITLE')
        with self.assertRaisesRegex(ValueError, 'selected_variant_unproven'):
            parse_detail(body.replace('"Gesigneerd"', '"Unknown option"'), row, AT)

    def test_real_load_more_contract_and_second_page(self):
        config, total, offset = load_more_config(LISTING)
        self.assertEqual((total, offset), (207, 24))
        t = Mock()
        t.get.return_value = LISTING
        # A distinct replay of card identities stands in for the public second page.
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(LISTING, 'html.parser')
        for c in soup.select('[data-atube-product-card]'):
            c['data-atube-product-id'] = '9' + c['data-atube-product-id']
            for a in c.select('a[href]'):
                a['href'] = a['href'].rstrip('/') + '-page-two/'
        t.more.return_value = {'html': str(soup), 'loaded': 48, 'total': 207, 'has_more': True}
        rows, state = catalogue(t, 2, AT)
        self.assertEqual(len(rows), 48)
        self.assertFalse(state['complete'])
        self.assertEqual(state['stop_reason'], 'pilot_page_limit')
        t.more.assert_called_once_with(config, 24)

    def test_repeated_page_and_external_endpoint_fail_closed(self):
        t = Mock()
        t.get.return_value = LISTING
        t.more.return_value = {'html': LISTING, 'loaded': 48, 'total': 207, 'has_more': True}
        with self.assertRaisesRegex(ValueError, 'repeated_product'):
            catalogue(t, 2, AT)
        with self.assertRaisesRegex(ValueError, 'unreviewed_load_more_endpoint'):
            load_more_config(LISTING.replace('https://www.atube-highfidelity.nl/wp-admin/admin-ajax.php', 'https://other.test/api'))

    def test_access_failure_stops_shop_and_preserves_listing_without_writes(self):
        t = Mock(requests=[])
        t.get.side_effect = [LISTING, RuntimeError('HTTP_403')]
        result = run(t, 'details', 1, 5)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(result['records']), 24)
        self.assertEqual(result['database_writes'], 0)
        self.assertEqual(t.get.call_count, 2)
        self.assertTrue(any(r['detail_status'] == 'technical_error' for r in result['records']))

    def test_album_queue_uses_own_adapter_without_requiring_product_jsonld(self):
        transport = Mock(requests=[])
        transport.get.return_value = DETAIL
        row = dict(product_url=self.doe['source_url'], source_product_id='64226', shop_domain='atube-highfidelity.nl',
                   source_input=dict(title_raw=self.doe['title_raw'], price='34.50', currency='EUR', price_source='listing', listing_observed_at=stamp()))
        source = verify_source(row, transport)
        self.assertEqual((source['route'], source['price']), ('EAN', '34.50'))
        self.assertEqual(source['artist'], 'Doe Maar')
        # An explicitly ancient observation must not be made fresh by a detail read.
        row['source_input']['listing_observed_at'] = '2000-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'fresh_listing_required'):
            verify_source(row, transport)

    def test_variant_refresh_keeps_variant_url_and_distinct_source_id(self):
        row = next(r for r in self.rows if r['source_product_id'] == '84727')
        transport = Mock(requests=[])
        transport.get.return_value = (FIXTURES / 'detail-anette.html').read_text()
        queued = dict(product_url=row['source_url'] + '?attribute_keuze=Gesigneerd', source_product_id='98254',
                      shop_domain='atube-highfidelity.nl', source_input=dict(title_raw=row['title_raw'], price='87.00', currency='EUR',
                      price_source='listing', listing_observed_at=stamp(), parent_product_id='84727'))
        source = verify_source(queued, transport)
        self.assertEqual(source['source_product_id'], '98254')
        self.assertIn('attribute_keuze=Gesigneerd', source['source_url'])
        queued['product_url'] = row['source_url'] + '?attribute_keuze=Ongesigneerd'
        with self.assertRaisesRegex(ValueError, 'requested_variant_conflict'):
            verify_source(queued, transport)


if __name__ == '__main__':
    unittest.main()
