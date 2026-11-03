import unittest
from scripts.scrapers.rarevinyl import normalize_gtin, parse_price, extract_cards, extract_detail

class RareVinylTests(unittest.TestCase):
    def test_gtin(self):
        self.assertEqual(normalize_gtin("4007196128446"), "4007196128446")
        self.assertIsNone(normalize_gtin("4007196128447"))
    def test_price(self):
        self.assertEqual(parse_price("39,99 €"), "39.99")
    def test_cards(self):
        html = '<article><a href="/products/sample">Artist - Album</a><span>Factory Sealed</span><span>39,99 €</span></article>'
        row = extract_cards(html)[0]
        self.assertTrue(row["sealed_signal"])
        self.assertEqual(row["price_eur"], "39.99")
    def test_detail(self):
        html = "<p>Barcode - 4007196128446</p><p>Condition - Factory sealed from new. This item is unplayed.</p>"
        row = extract_detail(html)
        self.assertTrue(row["sealed_confirmed"])
        self.assertEqual(row["condition_normalized"], "NEW")

if __name__ == "__main__":
    unittest.main()
