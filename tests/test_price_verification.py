import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from scripts.workers.price_evidence import assess, capture, amount
from scripts.workers.run_catalog_price import command_for, main


def row(index, price="25.00"):
    return {"source_url": f"https://test.invalid/product/{index}", "price": price, "currency": "EUR"}


class PriceVerificationTests(unittest.TestCase):
    def test_shipping_text_and_ambiguous_prices_are_never_amounts(self):
        for value in ("shipping 4.95", "25.00 + 4.95", "free", "NaN", "0", "-1", None):
            self.assertIsNone(amount(value))
        self.assertEqual(str(amount("€ 24,95")), "24.95")

    def test_three_equal_prices_are_allowed_but_large_dominance_needs_review(self):
        self.assertEqual(assess([row(i) for i in range(3)])[1]["status"], "green")
        self.assertEqual(assess([row(i) for i in range(1000)])[1]["status"], "red")
        self.assertEqual(assess([row(i, str(i % 50 + 10)) for i in range(1000)])[1]["status"], "green")

    def test_empty_missing_and_conflicting_prices_fail_closed(self):
        for records in ([], [row(0, None)], [row(0), row(0, "26.00")], [row(i, None) for i in range(20)] + [row(21)]):
            self.assertEqual(assess(records)[1]["status"], "red")

    def test_partial_catalogue_after_rate_limit_is_not_green(self):
        records = [row(0), {"kind": "source_error", "reason": "HTTP 429"}]
        self.assertEqual(assess(records)[1]["status"], "red")

    def test_source_commands_never_enable_details_or_native_writes(self):
        for file in Path(".github/workflows").glob("price-*.yml"):
            worker = file.stem.removeprefix("price-")
            command = command_for(worker, 0, write=True)
            self.assertNotIn("--write", command)
            self.assertNotIn("--run-detail", command)
            self.assertNotIn("--mode", command, worker)
        self.assertIn("discover_imusic_genres", " ".join(command_for("imusic", 0)))
        self.assertIn("discover_jpc_vinyl", " ".join(command_for("jpc", 0)))

    def run_worker(self, write, source_exit=0):
        with tempfile.TemporaryDirectory() as directory, \
             patch("scripts.workers.run_catalog_price.Path", side_effect=lambda path: Path(directory) / path), \
             patch("sys.argv", ["worker", "--worker", "suburban", "--limit", "0"] + (["--write"] if write else [])), \
             patch.dict(os.environ, {"DATABASE_URL": "do-not-pass-to-source"}), \
             patch("scripts.workers.price_database.update_existing", return_value={"updated": 1, "verified": 1}) as writer, \
             contextlib.redirect_stdout(io.StringIO()):
            def source(command, **kwargs):
                self.assertNotIn("--write", command)
                self.assertEqual(kwargs["env"]["DATABASE_URL"], "")
                with patch.dict(os.environ, kwargs["env"]):
                    capture(row(0))
                return Mock(returncode=source_exit)
            with patch("scripts.workers.run_catalog_price.subprocess.run", side_effect=source):
                result = main()
            summary = json.loads((Path(directory) / "output/price-verification/suburban/summary.json").read_text())
            return result, summary, writer.call_count

    def test_dry_run_collects_current_evidence_with_zero_database_writes(self):
        result, summary, calls = self.run_worker(False)
        self.assertEqual((result, calls, summary["database_writes"]), (0, 0, 0))

    def test_write_requires_successful_source_then_verifies_database(self):
        result, summary, calls = self.run_worker(True)
        self.assertEqual((result, calls, summary["database"]["verified"]), (0, 1, 1))
        result, summary, calls = self.run_worker(True, source_exit=1)
        self.assertEqual((result, calls, summary["status"]), (1, 0, "red"))


if __name__ == "__main__":
    unittest.main()
