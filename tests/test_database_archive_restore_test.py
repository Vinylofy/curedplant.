import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.workers.database_archive_restore_test import checkpoint_manifests


class RestoreArchiveTests(unittest.TestCase):
    def test_restore_query_casts_uuid_before_aggregation(self):
        source = Path("scripts/workers/database_archive_restore_test.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("min(id::text), max(id::text)", source)
        self.assertNotIn("min(id)::text", source)

    def test_only_checkpointed_checksum_verified_archives_are_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            root = destination / "v1" / "price_history" / "source"
            root.mkdir(parents=True)
            body = b'{"id":"00000000-0000-0000-0000-000000000001"}\n'
            archive = root / "batch.jsonl"
            archive.write_bytes(body)
            metadata = {"table": "price_history", "file": archive.name,
                        "sha256": hashlib.sha256(body).hexdigest(), "count": 1}
            (root / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
            (root / "checkpoint.json").write_text(json.dumps({
                "version": 1, "table": "price_history", "manifest": "manifest.json",
            }), encoding="utf-8")
            selected = checkpoint_manifests(destination, "price_history", 2)
            self.assertEqual(selected[0][0]["count"], 1)
            archive.write_bytes(body + body)
            with self.assertRaisesRegex(ValueError, "checksum"):
                checkpoint_manifests(destination, "price_history", 2)


if __name__ == "__main__":
    unittest.main()
