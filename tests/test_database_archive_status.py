import json
import tempfile
import unittest
from pathlib import Path

from scripts.workers.database_archive_status import archived_rows


class ArchiveStatusTests(unittest.TestCase):
    def test_sums_manifest_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            root = destination / "v1" / "price_history" / "source"
            root.mkdir(parents=True)
            for number, count in ((1, 10), (2, 20)):
                (root / f"batch-{number}.manifest.json").write_text(json.dumps({
                    "version": 1, "table": "price_history", "sha256": str(number),
                    "file": f"batch-{number}.jsonl", "count": count,
                }), encoding="utf-8")
            self.assertEqual(archived_rows(destination, "price_history"), 30)


if __name__ == "__main__":
    unittest.main()
