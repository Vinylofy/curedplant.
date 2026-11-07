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
            row = deepcopy(self.rows[0]); row["Format"] = value
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

    def test_observed_y_n_availability_and_product_link_identity(self):
        for value, expected in [("Y", "in_stock"), ("N", "out_of_stock"), ("unexpected", "unknown")]:
            row = deepcopy(self.rows[0]); row["OfferNL.isDeliverable"] = value
            self.assertEqual(self.select(row)[0][0]["availability"], expected)
        row = deepcopy(self.rows[0]); row["productId"] = "9999999999999999"
        offers, rejected = self.select(row)
        self.assertFalse(offers)
        self.assertEqual({r["reason"] for r in rejected}, {"product_identity_link_mismatch"})

    def test_future_or_unrecognised_release_date_never_claims_current_stock(self):
        for value in ["2099-11-20", "unrecognised"]:
            row = deepcopy(self.rows[0]); row["OfferNL.releaseDate"] = value
            self.assertEqual(self.select(row)[0][0]["availability"], "unknown")

    def test_no_free_personal_or_shipping_prose_as_price(self):
        for value in ["Gratis", "€2.95 shipping", "Na Select 12.99", "0", "NaN", "Infinity", "-1"]:
            with self.assertRaises(FeedError):
                amount(value)

    def test_links_are_encoded_site_scoped_and_country_checked(self):
        link = affiliate_link(self.rows[0]["productPageUrlBE"], "BE", "12345")
        query = parse_qs(urlsplit(link).query)
        self.assertEqual(query["s"], ["12345"])
        self.assertEqual(query["f"], ["pf"])
        self.assertEqual(query["url"], [self.rows[0]["productPageUrlBE"]])
        for value in [self.rows[0]["productPageUrlNL"], "https://bol.com.attacker.invalid/be/nl/p/a/123/",
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
        profile = {**PROFILE, "type": "xml", "format": "Properties.Drager"}
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

    def test_full_inspection_reports_observed_vocabulary_and_vinyl_candidates(self):
        from scripts.importers.bol_feed import inspect_schema
        report = inspect_schema(self.path, PROFILE)
        self.assertTrue(report["complete_feed"])
        self.assertEqual(report["vocabulary"]["Format"], {"LP": 20})
        self.assertEqual(len(report["vinyl_candidate_samples"]), 20)
        self.assertFalse(report["live_schema_verified"])
        bounded = inspect_schema(self.path, PROFILE, max_rows=5)
        self.assertFalse(bounded["complete_feed"])

    def test_truncated_gzip_pilot_cannot_pass_integrity(self):
        output = self.path.with_suffix(".json")
        compressed = self.path.with_suffix(".gz")
        compressed.write_bytes(gzip.compress(self.path.read_bytes())[:-8])
        with patch("scripts.importers.bol_feed.psycopg.connect") as connect:
            result = main(["--feed", str(compressed), "--profile", str(ROOT / "config/bol-feed.example.json"),
                           "--limit", "1", "--output", str(output)])
        self.assertEqual(result, 1)
        connect.assert_not_called()

    def test_checkpoint_only_after_success_and_unchanged_feed_does_not_write(self):
        profile = self.path.with_suffix(".profile.json")
        profile.write_text(json.dumps({**PROFILE, "live_schema_verified": True, "verified_markets": ["NL"]}))
        output = self.path.with_suffix(".report.json")
        state = self.path.with_suffix(".state.json")
        command = ["--profile", str(profile), "--limit", "0", "--state", str(state),
                   "--write", "--approve-publication", "--output", str(output)]
        def download(path, **kwargs):
            Path(path).write_bytes(self.path.read_bytes())
            return self.now
        with patch.dict("os.environ", {"BOL_SITE_ID": "12345", "DATABASE_URL": "test"}), patch(
                "scripts.importers.bol_feed.download_feed", side_effect=download), patch(
                "scripts.importers.bol_feed.publish", side_effect=FeedError("test_failure")):
            self.assertEqual(main(command), 1)
        self.assertFalse(state.exists())
        with patch.dict("os.environ", {"BOL_SITE_ID": "12345", "DATABASE_URL": "test"}), patch(
                "scripts.importers.bol_feed.download_feed", side_effect=download), patch(
                "scripts.importers.bol_feed.publish", return_value={"updated_offers": 20}):
            self.assertEqual(main(command), 0)
        self.assertTrue(state.exists())
        with patch.dict("os.environ", {"BOL_SITE_ID": "12345", "DATABASE_URL": "test"}), patch(
                "scripts.importers.bol_feed.download_feed", return_value=self.now), patch(
                "scripts.importers.bol_feed.publish") as writer:
            self.assertEqual(main(command), 0)
            writer.assert_not_called()
        self.assertEqual(json.loads(output.read_text())["status"], "unchanged_feed")

    def test_reviewed_pilot_checksum_mismatch_blocks_all_database_access(self):
        output = self.path.with_suffix(".checksum.json")
        with patch("scripts.importers.bol_feed.psycopg.connect") as connect, patch.dict(
                "os.environ", {"BOL_SITE_ID": "12345"}):
            result = main(["--feed", str(self.path), "--profile", str(ROOT / "config/bol-feed.live.json"),
                           "--write", "--approve-publication", "--source-at", self.now.isoformat(),
                           "--expected-feed-sha256", "0" * 64, "--output", str(output)])
        self.assertEqual(result, 1); connect.assert_not_called()
        self.assertEqual(json.loads(output.read_text())["errors"], ["reviewed_feed_checksum_mismatch"])

    def test_reviewed_pilot_keeps_checksum_market_link_and_size_guards(self):
        from scripts.importers.bol_feed import reviewed_pilot
        plan = build_plan(self.path, PROFILE, ["NL"], "12345", limit=20)
        plan.update(status="blocked", errors=["QueryCanceled"], feed_sha256="a" * 64)
        path = self.path.with_suffix(".review.json")
        path.write_text(json.dumps(plan))
        checked = reviewed_pilot(path, "a" * 64, "12345")
        self.assertEqual(len(checked["offers"]), 20)
        self.assertEqual(checked["errors"], [])
        for change, reason in [({"feed_sha256": "b" * 64}, "checksum"),
                               ({"errors": ["invalid_source"]}, "unsupported"),
                               ({"complete_feed": True}, "unsupported")]:
            altered = deepcopy(plan); altered.update(change); path.write_text(json.dumps(altered))
            with self.assertRaisesRegex(FeedError, reason):
                reviewed_pilot(path, "a" * 64, "12345")
        for field, value, reason in [("country", "BE", "market"), ("ean", "invalid", "identity"),
                                     ("product_url", "https://evil.invalid/", "affiliate")]:
            altered = deepcopy(plan); altered["offers"][0][field] = value
            path.write_text(json.dumps(altered))
            with self.assertRaisesRegex(FeedError, reason):
                reviewed_pilot(path, "a" * 64, "12345")
        altered = deepcopy(plan); altered["offers"].append(deepcopy(altered["offers"][0]))
        path.write_text(json.dumps(altered))
        with self.assertRaisesRegex(FeedError, "twenty"):
            reviewed_pilot(path, "a" * 64, "12345")

    def test_xml_external_entities_are_not_loaded(self):
        p = self.path.with_suffix(".xml")
        p.write_text('<!DOCTYPE root [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
                     '<Products><Product><title>&secret;</title></Product></Products>')
        with self.assertRaises(FeedError):
            list(rows_from(p, {**PROFILE, "type": "xml"}))


if __name__ == "__main__":
    unittest.main()
