import unittest

from scripts.scrapers.usf.jobs.discover_imusic_genres import GenreSpec, parse_listing_links


class IMusicListingPricesTests(unittest.TestCase):
    def parse(self, html):
        return parse_listing_links(html, listing_url="https://imusic.nl/page/search", genre=GenreSpec("76"), offset=0)

    def test_shipping_footer_never_replaces_price(self):
        html = '''<article class="search-teaser"><a href="/music/0889853577415/example">Album</a>
        <form><input name="itemId" value="0889853577415"><button class="teaser-cta">
        <span class="teaser-cta__price">€ 24,49</span></button></form></article>
        <footer>Gratis verzending vanaf € 100,00</footer>'''
        self.assertEqual(self.parse(html)[0].payload["listing_price_raw"], "24,49")

    def test_unbounded_link_or_mismatched_product_never_gets_price(self):
        html = '''<a href="/music/0889853577415/example">Album</a>
        <div>€ 24,49</div><footer>Gratis verzending vanaf € 100,00</footer>
        <article class="search-teaser"><a href="/music/0889853577415/example">Album</a>
        <input name="itemId" value="1234567890123"><button class="teaser-cta">
        <span class="teaser-cta__price">€ 100,00</span></button></article>'''
        self.assertNotIn("listing_price_raw", self.parse(html)[0].payload)

    def test_ambiguous_prices_not_selected(self):
        html = '''<article class="search-teaser"><a href="/music/0889853577415/example">Album</a>
        <input name="itemId" value="0889853577415"><button class="teaser-cta">
        <span class="teaser-cta__price">€ 24,49</span><span class="teaser-cta__price">€ 100,00</span>
        </button></article>'''
        self.assertNotIn("listing_price_raw", self.parse(html)[0].payload)


if __name__ == "__main__":
    unittest.main()
