import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.scrapers.usf.core.models import DiscoveredLink
from scripts.workers import run_catalog_price, run_ean_detail
from scripts.workers import run_windows_baseline as pilot

URL = "https://www.sounds-venlo.nl/4707526-fresku-leren-leven/"


def response(status, url=URL, html="", headers=None):
    result = requests.Response()
    result.status_code, result.url, result._content = status, url, html.encode()
    result.encoding = "utf-8"
    result.headers.update(headers or {})
    return result


class WindowsBaselineTests(unittest.TestCase):
    def test_copied_sources_have_original_hashes_and_windows_provenance(self):
        for shop in pilot.SHOPS:
            manifest, listing, detail = pilot.source_modules(shop)
            self.assertEqual(manifest["commit"], "c4b86b475c3af219b5f5dee77335c625af24605f")
            self.assertEqual(listing.SHOP_ID, shop)
            self.assertEqual(detail.SHOP_ID, shop)
        self.assertEqual(manifest["windows_runs"]["soundsvenlo"], 39029778437)

    def test_baseline_rejects_writes_before_subprocess_or_registry(self):
        for module in (run_catalog_price, run_ean_detail):
            with self.subTest(module=module.__name__), \
                 patch("sys.argv", ["worker", "--worker", "soundsvenlo", "--limit", "1",
                                    "--source-version", "windows-baseline", "--write"]), \
                 patch("subprocess.run") as process, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    module.main()
                process.assert_not_called()

    def test_unbounded_or_unsupported_requests_are_rejected(self):
        for shop, lane, limit in [("soundsvenlo", "price", 0), ("soundsvenlo", "price", 4),
                                  ("northendhaarlem", "detail", 26), ("another", "detail", 1)]:
            with self.assertRaises(SystemExit):
                pilot.command_for(shop, lane, limit)
        self.assertIn("scripts.workers.run_windows_baseline",
                      run_catalog_price.command_for("soundsvenlo", 1, "windows-baseline"))
        self.assertNotIn("--write", run_ean_detail.command_for("soundsvenlo", 5, False, "windows-baseline"))

    def test_original_north_end_fetch_uses_old_headers_and_one_attempt(self):
        _, listing, detail = pilot.source_modules("northendhaarlem")
        transport = pilot.BaselineTransport("northendhaarlem", listing, detail)
        url = listing.category_url(listing.CATEGORY_SEEDS[0], 1)
        with patch("requests.get", return_value=response(403, url, "blocked")) as fetch:
            with self.assertRaises(pilot.SourceBlocked):
                transport.fetch(url, "price")
            fetch.assert_called_once_with(url, headers=listing.REQUEST_HEADERS, timeout=(10, 45))
        self.assertEqual(transport.events[0]["status"], 403)

    def test_original_apex_product_link_is_accepted_without_rewriting(self):
        _, listing, detail = pilot.source_modules("northendhaarlem")
        transport = pilot.BaselineTransport("northendhaarlem", listing, detail)
        url = "https://northendhaarlem.nl/a-83247386/coloured-vinyl/album/"
        with patch.object(detail, "fetch_html", return_value=(200, "product")) as fetch:
            self.assertEqual(transport.fetch(url, "detail"), "product")
            fetch.assert_called_once_with(url, attempts=1)

    def test_original_venlo_listing_browser_is_used_but_429_does_not_retry(self):
        _, listing, detail = pilot.source_modules("soundsvenlo")
        transport = pilot.BaselineTransport("soundsvenlo", listing, detail, sleeper=Mock())
        url = listing.listing_url_for_page(1)
        with patch("requests.Session.get", return_value=response(403, url)), \
             patch.object(listing, "fetch_html_with_playwright", return_value="<main>catalog</main>") as browser:
            self.assertIn("catalog", transport.fetch(url, "price"))
            browser.assert_called_once_with(url, referer=None)
        transport.close()
        transport = pilot.BaselineTransport("soundsvenlo", listing, detail, sleeper=Mock())
        with patch("requests.Session.get", return_value=response(429, url)), \
             patch.object(listing, "fetch_html_with_playwright") as browser:
            with self.assertRaises(pilot.SourceBlocked):
                transport.fetch(url, "price")
            browser.assert_not_called()
        transport.close()

    def test_published_interval_remains_between_original_fetches(self):
        _, listing, detail = pilot.source_modules("northendhaarlem")
        sleep = Mock()
        transport = pilot.BaselineTransport("northendhaarlem", listing, detail,
                    clock=Mock(side_effect=[0, 5, 30]), sleeper=sleep)
        with patch.object(listing, "fetch_html", return_value=(200, "listing")):
            for _ in range(2):
                transport.fetch(listing.category_url(listing.CATEGORY_SEEDS[0], 1), "price")
        sleep.assert_called_once_with(25.0)

    def test_old_wrong_album_ean_is_observed_but_never_accepted(self):
        _, _, detail = pilot.source_modules("soundsvenlo")
        html = ('<main><div><hgroup><h1>Leren Leven</h1></hgroup><p>4707526</p></div></main>'
                '<aside><img src="/images/0602475004783-1.jpg"></aside>')
        link = DiscoveredLink("soundsvenlo", URL, payload={"price": "37.99"})
        record = pilot.detail_record("soundsvenlo", detail, html, link)
        self.assertEqual(record["baseline_gtin"], "00602475004783")
        self.assertTrue(record["identity_disagreement"])
        self.assertIsNone(record["ean"])

    def test_empty_catalog_and_http_block_are_red_and_saved_without_database(self):
        for status, html in [(200, "<html>no products</html>"), (403, "blocked")]:
            with tempfile.TemporaryDirectory() as temporary, \
                 patch("scripts.scrapers.usf.core.db.db_connection", side_effect=AssertionError("DB forbidden")), \
                 patch("requests.get", return_value=response(status, html=html)), \
                 patch.object(pilot, "Path", side_effect=lambda path: Path(temporary) / path), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pilot.run("northendhaarlem", "price", 1), 1)
                saved = json.loads((Path(temporary) / "output/windows-baseline/northendhaarlem-price.json").read_text())
                self.assertEqual(saved["status"], "red")
                self.assertEqual(saved["database_writes"], 0)
                if status == 403:
                    self.assertEqual(saved["source_access"], "blocked")
                    self.assertEqual(len(saved["transport"]), 1)

    def test_read_only_detail_pilot_does_real_fetches_and_rejects_old_wrong_ean(self):
        listing = ('<div class="group"><div><span>Fresku</span>'
                   '<a class="full-click" href="/4707526-fresku-leren-leven/">Leren Leven</a></div>'
                   '<p>LP € 37,99 Op voorraad</p></div>')
        detail = ('<main><div><hgroup><h1>Leren Leven</h1></hgroup><p>4707526</p></div></main>'
                  '<aside><img src="/images/0602475004783-1.jpg"></aside>')
        with tempfile.TemporaryDirectory() as temporary, \
             patch("requests.Session.get", side_effect=[response(200, html=listing), response(200, html=detail)]) as get, \
             patch("scripts.scrapers.usf.core.db.db_connection", side_effect=AssertionError("DB forbidden")), \
             patch.object(pilot, "Path", side_effect=lambda path: Path(temporary) / path), \
             patch.object(pilot.BaselineTransport, "pace"), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pilot.run("soundsvenlo", "detail", 1), 1)
            saved = json.loads((Path(temporary) / "output/windows-baseline/soundsvenlo-detail.json").read_text())
            self.assertEqual(get.call_count, 2)
            self.assertEqual(saved["fetched"], 1)
            self.assertEqual(saved["identity_disagreements"], 1)
            self.assertEqual(saved["records"][0]["listing_price"], "37.99")
            self.assertFalse(saved["write"])

    def test_own_product_barcode_can_pass_and_shipping_is_not_the_price(self):
        listing = ('<div class="group"><div><span>America</span>'
                   '<a class="full-click" href="/4818633-america-holiday-harmony/">Holiday Harmony</a></div>'
                   '<p>LP € 26,99 Op voorraad</p></div><footer>Verzending € 4,99</footer>')
        detail = ('<main><div><hgroup><h1>Holiday Harmony</h1></hgroup>'
                  '<p>0792755872161</p></div></main>')
        with tempfile.TemporaryDirectory() as temporary, \
             patch("requests.Session.get", side_effect=[response(200, html=listing), response(200, html=detail)]), \
             patch.object(pilot, "Path", side_effect=lambda path: Path(temporary) / path), \
             patch.object(pilot.BaselineTransport, "pace"), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pilot.run("soundsvenlo", "detail", 1), 0)
            saved = json.loads((Path(temporary) / "output/windows-baseline/soundsvenlo-detail.json").read_text())
            self.assertEqual(saved["status"], "green")
            self.assertEqual(saved["records"][0]["ean"], "00792755872161")
            self.assertEqual(saved["records"][0]["listing_price"], "26.99")


if __name__ == "__main__":
    unittest.main()
