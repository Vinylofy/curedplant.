from __future__ import annotations

import unittest

from unittest.mock import MagicMock, patch

from scripts.workers.muziker_catalog import CATALOG, parse_page, read_checkpoint, run


HTML = '''<a class="load-next-products" href="https://www.muziker.nl/vinyl-lps?page=2">next</a>
<div class="product-tile" data-product-code="349912">
 <a class="link-overlay" href="/black-sabbath-paranoid-vinyl-lp">
  <h4 class="product-tile-header">Black Sabbath - Paranoid (Vinyl LP)</h4>
  <p class="product-tile-sub-header">LP</p>
  <div class="tile-price"><div class="price">€ 26,99</div></div>
  <div class="stock-status green" title="Op voorraad">Op voorraad</div>
 </a>
</div>'''


class MuzikerCatalogTests(unittest.TestCase):
    def test_artist_title_listing_and_pagination(self):
        rows, next_url = parse_page(HTML, "https://www.muziker.nl/vinyl-lps", "now")
        self.assertEqual(next_url, "https://www.muziker.nl/vinyl-lps?page=2")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["artist"], rows[0]["title"], rows[0]["price"]),
                         ("Black Sabbath", "Paranoid (Vinyl LP)", "26.99"))
        self.assertEqual(rows[0]["availability"], "in_stock")

    def test_ean_is_never_created(self):
        rows, _ = parse_page(HTML, "https://www.muziker.nl/vinyl-lps", "now")
        self.assertNotIn("ean", rows[0])

    def test_unparseable_titles_and_prices_do_not_stop_valid_records(self):
        rejected = []
        bad_title = HTML.replace("Black Sabbath - Paranoid (Vinyl LP)", "Onbekend Vinyl LP").replace('/black-sabbath-paranoid-vinyl-lp', '/unknown')
        bad_price = HTML.replace("€ 26,99", "prijs onbekend").replace('/black-sabbath-paranoid-vinyl-lp', '/other')
        rows, _ = parse_page(HTML + bad_title + bad_price, CATALOG, "now", rejected)
        self.assertEqual(len(rows), 1)
        self.assertEqual([r['reason'] for r in rejected], ['artist_title_not_proven', 'price_not_proven'])

    def test_unknown_stock_is_not_assumed_in_stock(self):
        rows, _ = parse_page(HTML.replace('<div class="stock-status green" title="Op voorraad">Op voorraad</div>', ''), CATALOG, "now")
        self.assertEqual(rows[0]['availability'], 'unknown')

    def test_invalid_page_does_not_advance_checkpoint(self):
        with self.assertRaisesRegex(ValueError, 'catalog_page_has_no_product_tiles'):
            parse_page('<html>layout changed</html>', CATALOG, 'now')

    def test_checkpoint_resumes_or_restarts_after_completion(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = ('https://www.muziker.nl/vinyl-lps?page=3',)
        self.assertTrue(read_checkpoint(conn).endswith('page=3'))
        conn.execute.return_value.fetchone.return_value = (None,)
        self.assertEqual(read_checkpoint(conn), CATALOG)
        conn.execute.return_value.fetchone.return_value = ('https://www.muziker.nl/other',)
        with self.assertRaisesRegex(ValueError, 'invalid_checkpoint_path'):
            read_checkpoint(conn)

    @patch('scripts.workers.muziker_catalog.write_rows')
    @patch('scripts.workers.muziker_catalog.psycopg.connect')
    @patch('scripts.workers.muziker_catalog.Transport')
    @patch.dict('os.environ', {'DATABASE_URL': 'dummy'})
    def test_page_committed_before_next_page_fails(self, transport_cls, connect, write_rows):
        transport = transport_cls.return_value
        transport.get.side_effect = [HTML, RuntimeError('network failure')]
        conn = connect.return_value
        conn.execute.return_value.fetchone.return_value = None
        with self.assertRaisesRegex(RuntimeError, 'network failure'):
            run(2, True)
        self.assertEqual(write_rows.call_count, 1)
        self.assertTrue(write_rows.call_args.args[3].endswith('page=2'))
        conn.transaction.return_value.__exit__.assert_called()


if __name__ == "__main__":
    unittest.main()
