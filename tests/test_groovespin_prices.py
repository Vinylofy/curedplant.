import html
import json
import unittest
from unittest.mock import Mock

from scripts.workers.groovespin_catalog import BASE
from scripts.workers.groovespin_prices import crawl, exact_offer
from scripts.workers.price_evidence import url_key


START = BASE + "/albums?collection=vinyl"


def item(album, **changes):
    return {"id": album, "master_id": album, "productIds": [album], "items_count": 1,
            "release_id": album + 100, "url": f"{BASE}/album/example-{album}",
            "used": 0, "condition_id": 1, "price": "24,99 €", "formats": [{"name": "LP"}],
            "available": {"name_localised": "Op voorraad"}, **changes}


def page(number, items, following=None):
    data = {"component": "ProductListPage", "props": {"currentCurrency": "EUR", "masters": {
        "current_page": number, "has_exact_total": True, "last_page": 2, "total": 2,
        "data": items, "next_page_url": following}}}
    return '<div id="app" data-page="' + html.escape(json.dumps(data), quote=True) + '"></div>'


class GrooveSpinPricesTests(unittest.TestCase):
    def test_exact_new_vinyl_requires_release_and_price(self):
        self.assertEqual(exact_offer(item(1))["price"], "24.99")
        for changes in (
            {"used": 1}, {"condition_id": 2}, {"formats": [{"name": "CD"}]},
            {"productIds": [1, 2]}, {"items_count": 2}, {"price": "vanaf 24,99 €"},
            {"release_id": None},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(exact_offer(item(1, **changes)))

    def test_follows_catalogue_to_declared_end(self):
        source = Mock()
        source.get.side_effect = [page(1, [item(1)], START + "&page=2"), page(2, [item(2)])]
        offers, summary = crawl(source, START, 20)
        self.assertTrue(summary["complete"])
        self.assertEqual(len(offers), 2)

    def test_capped_run_stays_partial(self):
        source = Mock()
        source.get.return_value = page(1, [item(1)], START + "&page=2")
        self.assertFalse(crawl(source, START, 1)[1]["complete"])

    def test_pagination_cannot_drop_the_filter_or_repeat_an_album(self):
        source = Mock()
        source.get.return_value = page(1, [item(1)], BASE + "/albums?page=2")
        with self.assertRaisesRegex(ValueError, "filters"):
            crawl(source, START, 20)
        source.get.side_effect = [page(1, [item(1)], START + "&page=2"), page(2, [item(1)])]
        with self.assertRaisesRegex(ValueError, "repeated"):
            crawl(source, START, 20)

    def test_price_matching_preserves_release_identity(self):
        album = BASE + "/album/example-1"
        key = url_key(album + "?releaseId=101")
        self.assertEqual(key, url_key(album + "?src=listing&releaseId=101"))
        self.assertNotEqual(key, url_key(album + "?releaseId=102"))
        self.assertNotEqual(key, url_key(album))


if __name__ == "__main__":
    unittest.main()
