from __future__ import annotations

import unittest

from scripts.workers.muziker_catalog import parse_page


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


if __name__ == "__main__":
    unittest.main()
