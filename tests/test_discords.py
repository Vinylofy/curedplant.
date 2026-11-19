import copy
from datetime import datetime, timezone
import unittest

from scripts.importers.import_discords import SHOP_DEFINITION, map_discords_row
from scripts.importers.registry import get_shop_importer
from scripts.scrapers import discords
from scripts.workers.price_database import _ensure_discords_nl_shipping


NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)


def product(**overrides):
    value = {
        "id": 7629775765747,
        "handle": "amy-winehouse-back-to-black-lp-1",
        "title": "Amy Winehouse - Back To Black (LP)",
        "vendor": "Amy Winehouse",
        "product_type": "LP",
        "tags": ["nieuw"],
        "images": [{"src": "//cdn.shopify.com/cover.jpg"}],
        "variants": [{"id": 42623475974387, "price": "29.95", "compare_at_price": "34.95",
                      "available": True, "barcode": "602517341289"}],
    }
    value.update(overrides)
    return value


class DiscordsTests(unittest.TestCase):
    def test_nl_market_registration_uses_published_shipping_evidence(self):
        class Cursor:
            def execute(self, query, params):
                self.query, self.params = query, params

        cursor = Cursor()
        _ensure_discords_nl_shipping(cursor, "shop-id")
        self.assertEqual(cursor.params, ("shop-id",))
        self.assertIn("'NL','confirmed'", cursor.query)
        self.assertIn("https://discords.nl/policies/shipping-policy", cursor.query)
        self.assertIn("on conflict (shop_id,country_code)", cursor.query)

    def test_listing_is_new_lp_only_and_keeps_listing_price(self):
        row = discords.listing_record(product(), page=1, seen_at=NOW)
        self.assertEqual((row["artist"], row["title"], row["price"], row["compare_at_price"]),
                         ("Amy Winehouse", "Back To Black", "29.95", "34.95"))
        self.assertEqual(row["availability"], "in_stock")
        self.assertFalse(row["ean"])
        self.assertIsNone(discords.listing_record(product(product_type="CD"), page=1, seen_at=NOW))
        self.assertIsNone(discords.listing_record(product(tags=["Tweedehands"]), page=1, seen_at=NOW))

    def test_detail_requires_same_product_and_variant_and_valid_unique_gtin(self):
        listing = discords.listing_record(product(), page=1, seen_at=NOW)
        detail = discords.detail_record(product(images=["//cdn.shopify.com/detail.jpg"]), listing)
        self.assertEqual(detail["ean"], "00602517341289")
        self.assertEqual(detail["price"], "29.95")
        self.assertEqual(detail["image_url"], "https://cdn.shopify.com/detail.jpg")
        with self.assertRaisesRegex(ValueError, "product identity"):
            discords.detail_record(product(id=1), listing)
        with self.assertRaisesRegex(ValueError, "variant"):
            discords.detail_record(product(variants=[]), listing)

    def test_invalid_or_conflicting_barcode_fails_closed(self):
        listing = discords.listing_record(product(), page=1, seen_at=NOW)
        invalid = product()
        invalid["variants"][0]["barcode"] = "602517341280"
        result = discords.detail_record(invalid, listing)
        self.assertEqual((result["ean"], result["detail_issue"]),
                         ("", "missing_or_ambiguous_variant_gtin"))
        listing["variant_id"] = ""
        conflicting = product(variants=[
            {"id": 1, "price": 20, "available": True, "barcode": "602517341289"},
            {"id": 2, "price": 21, "available": True, "barcode": "0602445542246"},
        ])
        result = discords.detail_record(conflicting, listing)
        self.assertEqual(result["ean"], "")

    def test_detail_does_not_mutate_listing_and_importer_is_strict(self):
        listing = discords.listing_record(product(), page=1, seen_at=NOW)
        original = copy.deepcopy(listing)
        enriched = discords.detail_record(product(), listing)
        self.assertEqual(listing, original)
        record, error = map_discords_row(enriched, 2)
        self.assertIsNone(error)
        self.assertEqual((record.ean, str(record.price), record.is_secondhand),
                         ("00602517341289", "29.95", False))
        bad, error = map_discords_row({**enriched, "ean": "602517341280"}, 2)
        self.assertIsNone(bad)
        self.assertEqual(error, "missing_or_invalid_ean")
        self.assertIs(get_shop_importer("discords"), SHOP_DEFINITION)


if __name__ == "__main__":
    unittest.main()
