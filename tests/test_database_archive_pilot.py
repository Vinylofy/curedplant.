"""Checkpoint validation must stop safely instead of skipping source rows."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.workers.database_archive_pilot import read_checkpoint, write_checkpoint


class ArchiveCheckpointTests(unittest.TestCase):
    def test_checkpoint_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = b'{"id":"00000000-0000-0000-0000-000000000001"}\n'
            archive = root / "batch.jsonl"
            archive.write_bytes(body)
            metadata = {
                "file": archive.name,
                "sha256": hashlib.sha256(body).hexdigest(),
                "last_scraped_at": "2026-11-14T00:00:00+00:00",
                "last_id": "00000000-0000-0000-0000-000000000001",
            }
            manifest = root / "batch.manifest.json"
            manifest.write_text(json.dumps(metadata), encoding="utf-8")
            write_checkpoint(root, metadata, manifest)
            self.assertEqual(read_checkpoint(root), (metadata["last_scraped_at"], metadata["last_id"]))
            archive.write_bytes(body + body)
            with self.assertRaisesRegex(ValueError, "corrupt"):
                read_checkpoint(root)

    def test_checkpoint_cannot_skip_past_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = b'{}\n'
            (root / "batch.jsonl").write_bytes(body)
            manifest = root / "batch.manifest.json"
            manifest.write_text(json.dumps({
                "file": "batch.jsonl", "sha256": hashlib.sha256(body).hexdigest(),
                "last_scraped_at": "2026-11-14T00:00:00+00:00", "last_id": "one",
            }), encoding="utf-8")
            write_checkpoint(root, {"last_scraped_at": "2026-11-15T00:00:00+00:00", "last_id": "two"}, manifest)
            with self.assertRaisesRegex(ValueError, "does not match"):
                read_checkpoint(root)


if __name__ == "__main__":
    unittest.main()
