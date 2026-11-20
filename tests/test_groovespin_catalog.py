import json
import unittest
from unittest.mock import Mock, patch

from scripts.workers.ean_progress import initial_state, reserve
from scripts.workers.groovespin_catalog import BASE, Blocked, Source, parse_offers


class GrooveSpinCatalogTests(unittest.TestCase):
    def test_offer_stays_with_its_release_and_preserves_backorder(self):
        url = BASE + "/album/example-42"
        release = url + "?releaseId=23"
        condition = "https://schema.org/NewCondition"
        product = {"@type": "Product", "name": "2LP Example", "url": release,
                   "gtin13": "5400863173166", "itemCondition": condition,
                   "offers": {"@type": "Offer", "url": release, "price": "42.99",
                              "priceCurrency": "EUR", "itemCondition": condition,
                              "availability": "https://schema.org/BackOrder"}}
        data = {"@graph": [{"@type": "MusicAlbum", "name": "Example", "byArtist": {"name": "Artist"}},
                           product, {**product, "name": "CD Example"},
                           {**product, "itemCondition": "https://schema.org/UsedCondition"},
                           {**product, "url": url + "?releaseId=24"}]}
        body = f'<script type="application/ld+json">{json.dumps(data)}</script>'
        rows = list(parse_offers(body, url, "2026-11-20T09:00:00Z"))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["url"], rows[0]["ean"], rows[0]["availability"]),
                         (release, "5400863173166", "unknown"))

    def test_disallowed_query_does_not_reach_transport(self):
        session = Mock()
        session.headers = {}
        session.get.return_value.status_code = 200
        session.get.return_value.text = (
            "User-agent: *\nAllow: /\n\nUser-agent: *\nDisallow: /*?*formats\n"
        )
        with patch("scripts.workers.groovespin_catalog.time.sleep"):
            source = Source(session)
            with self.assertRaises(Blocked):
                source.get(BASE + "/albums?formats%5B%5D=1")
        self.assertEqual(session.get.call_count, 1)

    def test_four_batches_exhaust_the_daily_budget(self):
        state = initial_state("groovespin")
        self.assertEqual([reserve(state, 250, "2026-11-20") for _ in range(5)],
                         [250, 250, 250, 250, 0])
        self.assertEqual(reserve(state, 250, "2026-11-21"), 250)


if __name__ == "__main__":
    unittest.main()
