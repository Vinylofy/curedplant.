import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.scrapers.usf.core.models import DiscoveredLink
from scripts.scrapers.usf.jobs import live_price_pilot as pilot
from scripts.workers.run_catalog_price import command_for


class PricePilotTests(unittest.TestCase):
    def test_read_only_prices_use_live_pilot_and_writes_keep_native_worker(self):
        for shop in ("northendhaarlem", "soundsvenlo"):
            self.assertIn("scripts.scrapers.usf.jobs.live_price_pilot", command_for(shop, 1))
            self.assertIn(f"scripts.scrapers.usf.jobs.refresh_{shop}_listing_prices",
                          command_for(shop, 1, write=True))

    def test_empty_and_blocked_prices_cannot_be_green(self):
        for result in ([], RuntimeError("HTTP 403")):
            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(pilot, "Path", side_effect=lambda path: Path(directory) / path), \
                 patch.object(pilot, "new_session", return_value=Mock(events=[])), \
                 patch("scripts.scrapers.usf.jobs.refresh_northendhaarlem_listing_prices.discover_listing_rows",
                       **({"side_effect": result} if isinstance(result, Exception) else {"return_value": result})), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pilot.run("northendhaarlem", 1), 1)
                saved = json.loads((Path(directory) / "output/price-pilots/northendhaarlem.json").read_text())
                self.assertEqual(saved["status"], "red")
                self.assertEqual(saved["products"], 0)
                self.assertFalse(saved["write"])

    def test_actual_listing_prices_are_saved_without_database_calls(self):
        links = [DiscoveredLink("soundsvenlo", f"https://www.sounds-venlo.nl/product-{i}/",
                 payload={"price": price, "title": "LP", "availability": "in_stock"})
                 for i, price in enumerate(["26.99", "37.99"])]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(pilot, "Path", side_effect=lambda path: Path(directory) / path), \
             patch.object(pilot, "new_session", return_value=Mock(events=[])), \
             patch("scripts.scrapers.usf.jobs.refresh_soundsvenlo_listing_prices.fetch_listing_html", return_value="html"), \
             patch("scripts.scrapers.usf.jobs.refresh_soundsvenlo_listing_prices.parse_listing_page", return_value=(links, [])), \
             patch("scripts.scrapers.usf.core.db.db_connection", side_effect=AssertionError("DB forbidden")), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pilot.run("soundsvenlo", 1), 0)
            saved = json.loads((Path(directory) / "output/price-pilots/soundsvenlo.json").read_text())
            self.assertEqual(saved["products"], 2)
            self.assertEqual(saved["unique_prices"], 2)
            self.assertEqual([row["price"] for row in saved["records"]], ["26.99", "37.99"])
