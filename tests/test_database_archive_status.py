import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.workers.database_archive_status import archived_rows
from scripts.workers.database_archive_full import retention_days


class ArchiveStatusTests(unittest.TestCase):
    def test_status_retention_helper_reports_new_price_window(self):
        measured_at = datetime(2026, 11, 19, tzinfo=timezone.utc)
        self.assertEqual(retention_days("price_history", measured_at), 34)

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
