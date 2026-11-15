import os
import unittest
from unittest.mock import patch

from scripts.workers.database_archive_cleanup import delete_chunk, require_redundancy_confirmation


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

    def test_requires_matching_independent_copy_attestation(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "independent"):
                require_redundancy_confirmation("INDEPENDENT_COPY_VERIFIED")
        with patch.dict(os.environ, {
            "ARCHIVE_REDUNDANCY_ATTESTED": "INDEPENDENT_COPY_VERIFIED"
        }, clear=True):
            require_redundancy_confirmation("INDEPENDENT_COPY_VERIFIED")


if __name__ == "__main__":
    unittest.main()
