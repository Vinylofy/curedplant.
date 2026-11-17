import unittest

from scripts.scrapers.usf.jobs.detail_everythingjazz import parse_detail


EAN = "0199957690102"
URL = "https://eustore.everythingjazz.com/products/amy-winehouse-back-to-black-20-124297.js"


def link(product_type="Deluxe Clear Vinyl 3LP"):
    return {"payload": {"product_type": product_type, "title": "Back To Black 20",
                         "artist": "Amy Winehouse", "price": "59.99",
                         "availability": "in_stock"}}


def detail(product_type=None):
    return {"type": product_type, "title": "Back To Black 20", "vendor": "Amy Winehouse",
            "available": True, "variants": [{"barcode": EAN, "available": True, "sku": "524935000"}]}


class EverythingJazzDetailTests(unittest.TestCase):
    def test_missing_detail_type_uses_validated_listing_vinyl_type(self):
        result = parse_detail(link=link(), payload=detail(), detail_url=URL)
        self.assertEqual(result["ean_raw"], EAN)
        self.assertIsNone(result["payload"]["detail_issue"])
        self.assertEqual(result["payload"]["product_type"], "Deluxe Clear Vinyl 3LP")
        self.assertEqual(result["price_raw"], "59.99")

    def test_explicit_non_vinyl_detail_type_is_not_overridden(self):
        result = parse_detail(link=link(), payload=detail("CD"), detail_url=URL)
        self.assertIsNone(result["ean_raw"])
        self.assertEqual(result["payload"]["detail_issue"], "unsupported_product_type")

    def test_missing_type_on_both_sources_still_fails_closed(self):
        result = parse_detail(link=link(""), payload=detail(), detail_url=URL)
        self.assertIsNone(result["ean_raw"])
        self.assertEqual(result["payload"]["detail_issue"], "unsupported_product_type")


if __name__ == "__main__":
    unittest.main()
