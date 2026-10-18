from copy import deepcopy
import csv
from datetime import datetime, timezone
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from scripts.importers.bol_feed import (
    FeedError, affiliate_link, amount, build_plan, main, publish, rows_from, select_product,
)

ROOT = Path(__file__).parents[1]
PROFILE = json.loads((ROOT / "config/bol-feed.example.json").read_text())
spec = importlib.util.spec_from_file_location("bol_demo", Path(__file__).with_name("bol_demo.py"))
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class BolFeedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "synthetic.csv"
        demo.generate(self.path)
        self.rows = list(rows_from(self.path, PROFILE))
        self.now = datetime.now(timezone.utc)

    def select(self, row):
        return select_product(row, PROFILE, ["NL", "BE"], "12345", self.now)

    def test_twenty_synthetic_products_have_forty_separate_market_offers(self):
        plan = build_plan(self.path, PROFILE, ["NL", "BE"], "12345", limit=0)
        self.assertEqual((plan["selected_new_vinyl"], len(plan["offers"])), (20, 40))
        self.assertTrue(plan["complete_feed"])
        self.assertEqual(plan["database_writes"], 0)
        nl, be = plan["offers"][:2]
        self.assertEqual(nl["gtin"], be["gtin"])
        self.assertNotEqual(nl["price"], be["price"])
        self.assertIn("/be/nl/", parse_qs(urlsplit(be["product_url"]).query)["url"][0])

    def test_pilot_never_claims_complete_feed(self):
        plan = build_plan(self.path, PROFILE, ["NL"], "12345", limit=5)
        self.assertFalse(plan["complete_feed"])
        self.assertEqual(plan["selected_new_vinyl"], 5)

    def test_no_offer_is_copied_between_countries(self):
        row = self.rows[0]; row["OfferBE.sellingPrice"] = ""
        offers, skipped = self.select(row)
        self.assertEqual([o["country"] for o in offers], ["NL"])
        self.assertEqual(skipped[0]["reason"], "no_market_offer")

    def test_requires_explicit_new_condition_and_vinyl(self):
        for value in ["", "USED", "SECOND_HAND"]:
            row = deepcopy(self.rows[0]); row["OfferNL.condition"] = value
            offers, skipped = self.select(row)
            self.assertEqual([o["country"] for o in offers], ["BE"])
            self.assertEqual(skipped[0]["reason"], "condition_not_proven_new")
        for value in ["CD", "DVD", "Vinyl stand", "", "LP+CD"]:
            row = deepcopy(self.rows[0]); row["Properties.Drager"] = value
            with self.assertRaisesRegex(FeedError, "format_not_proven_vinyl"):
                self.select(row)

    def test_explicit_main_vinyl_box_value_can_be_configured(self):
        p = deepcopy(PROFILE); p["vinyl_values"].append("Vinyl boxset + bonus CD")
        row = self.rows[0]; row[p["format"]] = "Vinyl boxset + bonus CD"
        self.assertEqual(len(select_product(row, p, ["NL"], "12345", self.now)[0]), 1)

    def test_payable_price_wins_over_list_price_and_shipping(self):
        row = self.rows[0]; row["OfferNL.listPrice"] = "99.99"
        row["OfferNL.sellingPrice"] = "19.95"; row["OfferNL.shippingCost"] = "4.95"
        offer = self.select(row)[0][0]
        self.assertEqual((offer["price"], offer["shipping"]), ("19.95", "4.95"))

    def test_unknown_shipping_is_never_zero(self):
        row = self.rows[0]; row["OfferNL.shippingCost"] = ""
        offer = self.select(row)[0][0]
        self.assertIsNone(offer["shipping"])
        self.assertEqual(offer["shipping_status"], "unknown")

    def test_barcode_checkdigit_leading_zeros_and_no_fuzzy_matching(self):
        row = self.rows[1]
        self.assertTrue(self.select(row)[0][0]["ean"].startswith("000"))
        row["ean"] = "invalid barcode"
        with self.assertRaisesRegex(FeedError, "invalid_barcode"):
            self.select(row)

    def test_no_free_personal_or_shipping_prose_as_price(self):
        for value in ["Gratis", "€2.95 shipping", "Na Select 12.99", "0", "NaN", "Infinity", "-1"]:
            with self.assertRaises(FeedError):
                amount(value)

    def test_links_are_encoded_site_scoped_and_country_checked(self):
        link = affiliate_link(self.rows[0]["productUrlBE"], "BE", "12345")
        query = parse_qs(urlsplit(link).query)
        self.assertEqual(query["s"], ["12345"])
        self.assertEqual(query["f"], ["pf"])
        self.assertEqual(query["url"], [self.rows[0]["productUrlBE"]])
        for value in [self.rows[0]["productUrlNL"], "https://bol.com.attacker.invalid/be/nl/p/a/123/",
                      "https://www.bol.com/be/nl/p/a/123/?token=secret"]:
            with self.assertRaises(FeedError):
                affiliate_link(value, "BE", "12345")

    def test_conflicting_duplicate_barcode_market_is_quarantined(self):
        row = deepcopy(self.rows[0]); row["OfferNL.sellingPrice"] = "1.00"
        with self.path.open("w", newline="") as stream:
            w = csv.DictWriter(stream, self.rows[0].keys(), delimiter="|")
            w.writeheader(); w.writerows([self.rows[0], row])
        plan = build_plan(self.path, PROFILE, ["NL", "BE"], "12345", limit=0)
        self.assertEqual([o["country"] for o in plan["offers"]], ["BE"])
        self.assertEqual(plan["skipped"]["conflicting_offer_for_barcode_market"], 1)

    def test_gzip_and_partial_download_failure(self):
        p = self.path.with_suffix(".csv.gz")
        p.write_bytes(gzip.compress(self.path.read_bytes()))
        self.assertEqual(len(list(rows_from(p, PROFILE))), 20)
        p.write_bytes(p.read_bytes()[:-8])
        with self.assertRaises(EOFError):
            build_plan(p, PROFILE, ["NL"], "12345", limit=0)

    def test_xml_offer_fields_and_properties_use_same_selector(self):
        row = self.rows[0]
        p = self.path.with_suffix(".xml")
        parts = [f"<{k}>{v}</{k}>" for k, v in row.items() if "." not in k]
        for country in ["NL", "BE"]:
            parts.append(f"<Offer{country}>" + "".join(
                f"<{k.split('.')[1]}>{v}</{k.split('.')[1]}>" for k, v in row.items()
                if k.startswith("Offer" + country + ".")) + f"</Offer{country}>")
        parts.append("<Properties><Property><key>Drager</key><value>LP</value></Property></Properties>")
        p.write_text('<Products xmlns="urn:bol:test"><Product>' + "".join(parts) + '</Product></Products>')
        profile = {**PROFILE, "type": "xml"}
        plan = build_plan(p, profile, ["NL", "BE"], "12345", limit=0)
        self.assertEqual(len(plan["offers"]), 2)

    def test_dry_run_never_connects_even_if_database_configured(self):
        output = Path(self.directory.name) / "report.json"
        with patch("scripts.importers.bol_feed.psycopg.connect") as connect, patch.dict(
                "os.environ", {"BOL_SITE_ID": "12345", "DATABASE_URL": "secret"}):
            result = main(["--feed", str(self.path), "--profile", str(ROOT / "config/bol-feed.example.json"),
                           "--output", str(output)])
        self.assertEqual(result, 0); connect.assert_not_called()
        self.assertEqual(json.loads(output.read_text())["database_writes"], 0)

    def test_publication_requires_both_live_schema_and_explicit_approval(self):
        with self.assertRaisesRegex(FeedError, "explicit_approval"):
            publish({"offers": []}, "", {}, approved=False)
        with patch("scripts.importers.bol_feed.psycopg.connect") as connect:
            result = main(["--profile", str(ROOT / "config/bol-feed.example.json"),
                           "--write", "--output", str(Path(self.directory.name) / "blocked.json")])
        self.assertEqual(result, 1); connect.assert_not_called()

    def test_invalid_markets_and_missing_headers_fail_before_writes(self):
        with self.assertRaises(FeedError):
            build_plan(self.path, PROFILE, ["US"], "12345")
        self.path.write_text("ean|title\n123|x\n")
        with self.assertRaisesRegex(FeedError, "headers"):
            build_plan(self.path, PROFILE, ["NL"], "12345")

    def test_schema_inspection_does_not_need_a_speculative_format_header(self):
        p = self.path.with_name("unknown.csv")
        p.write_text("productId|ean|actualMediumName|OfferNL.condition\n123|0000000000017|LP|new\n")
        output = p.with_suffix(".json")
        with patch("scripts.importers.bol_feed.psycopg.connect") as connect:
            result = main(["--feed", str(p), "--profile", str(ROOT / "config/bol-feed.example.json"),
                           "--inspect-schema", "--output", str(output)])
        self.assertEqual(result, 0); connect.assert_not_called()
        self.assertIn("actualMediumName", json.loads(output.read_text())["headers"])

    def test_xml_external_entities_are_not_loaded(self):
        p = self.path.with_suffix(".xml")
        p.write_text('<!DOCTYPE root [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
                     '<Products><Product><title>&secret;</title></Product></Products>')
        with self.assertRaises(FeedError):
            list(rows_from(p, {**PROFILE, "type": "xml"}))


if __name__ == "__main__":
    unittest.main()
