import unittest

from bs4 import BeautifulSoup

from scripts.scrapers.legacy.platomania_legacy import (
    listing_cards,
    parse_article,
    parse_details_from_content,
)


class PlatomaniaLayoutTest(unittest.TestCase):
    def test_current_listing_card(self):
        soup = BeautifulSoup(
            """
            <div class="product-card">
              <a href="/artiest/lamar_kendrick">LAMAR, KENDRICK</a>
              <a href="/article/11744151/mr_morale/lamar_kendrick"
                 data-select-item='{"artist":"LAMAR, KENDRICK","format":"LP","price":"44.99","title":"MR. MORALE"}'>MR. MORALE</a>
              <span data-testid="article-price">€ 44,99</span>
              <div data-testid="card-stock">Op voorraad</div>
            </div>
            """,
            "html.parser",
        )
        cards = listing_cards(soup)
        self.assertEqual(len(cards), 1)
        row = parse_article(cards[0], "vinyl", "https://www.platomania.nl/vinyl", False)
        self.assertEqual(row["url"], "https://www.platomania.nl/article/11744151/mr_morale/lamar_kendrick")
        self.assertEqual(row["artist"], "LAMAR, KENDRICK")
        self.assertEqual(row["title"], "MR. MORALE")
        self.assertEqual(row["drager"], "LP")
        self.assertEqual(row["prijs"], "44,99")
        self.assertEqual(row["op_voorraad"], "JA")

    def test_current_product_schema_and_table(self):
        soup = BeautifulSoup(
            """
            <script type="application/ld+json">
            {"@context":"https://schema.org/","@type":"Product","brand":{"@type":"Brand","name":"INTERSCOPE"},
             "gtin13":"0602445926015","sku":"11744151","subjectOf":{"@type":"MusicAlbum","datePublished":"2022-08-26"}}
            </script>
            <table><tr><td>Item-nr</td><td>4406484 · EAN 0602445926015</td></tr></table>
            """,
            "html.parser",
        )
        self.assertEqual(
            parse_details_from_content(soup),
            {
                "label": "INTERSCOPE",
                "releasedatum": "2022-08-26",
                "herkomst": "",
                "item_nr": "4406484",
                "ean": "0602445926015",
            },
        )

    def test_legacy_layout_remains_supported(self):
        soup = BeautifulSoup('<article class="article"></article>', "html.parser")
        self.assertEqual(len(listing_cards(soup)), 1)


if __name__ == "__main__":
    unittest.main()
