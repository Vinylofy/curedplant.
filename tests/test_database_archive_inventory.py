import unittest
from unittest.mock import Mock

from scripts.workers.database_archive_inventory import collect


class InventoryTests(unittest.TestCase):
    def test_inventory_is_read_only_and_contains_restore_contract(self):
        cursor = Mock()
        cursor.fetchall.side_effect = [
            [("raw_shop_scrapes", 1000, 20, 2), ("price_history", 2000, 30, 3)],
            [("raw_shop_scrapes", "id", "uuid", "uuid", "NO")],
            [("raw_shop_scrapes", "raw_pkey", "CREATE UNIQUE INDEX raw_pkey", 50)],
            [("public.raw_shop_scrapes", "public.staged_offers", "raw_fk", "FOREIGN KEY")],
            [("00000000-0000-0000-0000-000000000001", "Example")],
        ]
        cursor.fetchone.side_effect = [(None, None), (None, None)]
        conn = Mock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=None)
        report = collect(conn)
        self.assertEqual(report["tables"]["raw_shop_scrapes"]["total_bytes"], 1000)
        self.assertEqual(report["tables"]["raw_shop_scrapes"]["columns"][0]["name"], "id")
        self.assertEqual(report["tables"]["raw_shop_scrapes"]["referenced_by"][0]["table"], "public.staged_offers")
        statements = [call.args[0].strip().lower() for call in cursor.execute.call_args_list]
        self.assertEqual(statements[0], "set transaction read only")
        self.assertFalse(any(s.startswith(("insert ", "update ", "delete ", "truncate ")) for s in statements))


if __name__ == "__main__":
    unittest.main()
