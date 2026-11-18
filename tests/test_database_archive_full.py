import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.workers.database_archive_full import (
    paths, read_checkpoint, retention_days, source_key, write_checkpoint,
)


class FullArchiveTests(unittest.TestCase):
    def test_price_retention_switches_to_34_days_on_19_november(self):
        before = datetime(2026, 11, 18, 23, 59, 59, tzinfo=timezone.utc)
        effective = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(retention_days("price_history", before), 90)
        self.assertEqual(retention_days("price_history", effective), 34)
        self.assertEqual(retention_days("raw_shop_scrapes", effective), 30)

    def test_retention_rejects_unknown_table_and_naive_time(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            retention_days("other")
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            retention_days("price_history", datetime(2026, 11, 19))

    def test_source_paths_are_stable_and_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, _ = paths(root, "raw_shop_scrapes", "shop")
            price, _ = paths(root, "price_history", "shop")
            self.assertNotEqual(raw, price)
            self.assertEqual(source_key("price_history", "shop"), source_key("price_history", "shop"))

    def test_verified_checkpoint_roundtrip_and_corruption_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            root, checkpoint = paths(destination, "price_history", "shop")
            root.mkdir(parents=True)
            body = b'{"id":"00000000-0000-0000-0000-000000000001"}\n'
            archive = root / "batch.jsonl"
            archive.write_bytes(body)
            metadata = {"version": 1, "table": "price_history", "shop_id": "shop",
                        "file": archive.name, "sha256": hashlib.sha256(body).hexdigest(),
                        "last_timestamp": "2026-01-01T00:00:00+00:00",
                        "last_id": "00000000-0000-0000-0000-000000000001"}
            manifest = root / "batch.manifest.json"
            manifest.write_text(json.dumps(metadata), encoding="utf-8")
            write_checkpoint(root, checkpoint, metadata, manifest)
            self.assertEqual(read_checkpoint(root, checkpoint, "price_history", "shop"),
                             (metadata["last_timestamp"], metadata["last_id"]))
            archive.write_bytes(body + body)
            with self.assertRaisesRegex(ValueError, "corrupt"):
                read_checkpoint(root, checkpoint, "price_history", "shop")


if __name__ == "__main__":
    unittest.main()
