import unittest

from scripts.workers.database_archive_cleanup import delete_chunk, require_cleanup_confirmation


class Cursor:
    def __init__(self):
        self.query = ""

    def execute(self, query, _parameters):
        self.query = query

    def fetchall(self):
        return []


class ArchiveCleanupTests(unittest.TestCase):
    def test_raw_and_price_safety_predicates_are_mandatory(self):
        raw = Cursor()
        delete_chunk(raw, "raw_shop_scrapes", ["id"])
        self.assertIn("staged_offers", raw.query)
        self.assertIn("not exists", raw.query.lower())
        price = Cursor()
        delete_chunk(price, "price_history", ["id"])
        self.assertIn("newer.product_id = p.product_id", price.query)
        self.assertIn("newer.shop_id = p.shop_id", price.query)

    def test_requires_explicit_single_copy_risk_acceptance(self):
        with self.assertRaisesRegex(RuntimeError, "single-copy"):
            require_cleanup_confirmation("INDEPENDENT_COPY_VERIFIED")
        require_cleanup_confirmation("SINGLE_E_COPY_RISK_ACCEPTED")


if __name__ == "__main__":
    unittest.main()
