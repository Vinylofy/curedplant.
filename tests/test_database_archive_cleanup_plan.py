import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.workers.database_archive_cleanup_plan import archive_ids, verified_manifests


class CleanupPlanTests(unittest.TestCase):
    def test_selects_only_valid_unique_archived_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            root = destination / "v1" / "raw_shop_scrapes" / "source"
            root.mkdir(parents=True)
            body = b'{"id":"00000000-0000-0000-0000-000000000001"}\n'
            archive = root / "batch-a.jsonl"
            archive.write_bytes(body)
            manifest = root / "batch-a.manifest.json"
            manifest.write_text(json.dumps({
                "version": 1, "table": "raw_shop_scrapes", "file": archive.name,
                "sha256": hashlib.sha256(body).hexdigest(), "count": 1,
            }), encoding="utf-8")
            selected = verified_manifests(destination, "raw_shop_scrapes", 10)
            self.assertEqual(archive_ids(*selected[0]), ["00000000-0000-0000-0000-000000000001"])
            archive.write_bytes(body + body)
            with self.assertRaisesRegex(ValueError, "checksum"):
                verified_manifests(destination, "raw_shop_scrapes", 10)


if __name__ == "__main__":
    unittest.main()
