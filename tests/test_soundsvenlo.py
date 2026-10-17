import json
import unittest
from unittest.mock import Mock, patch
import requests

from scripts.scrapers.usf.core.soundsvenlo_transport import SoundsVenloSession, canonical_url
from scripts.scrapers.usf.jobs.detail_soundsvenlo import ean_evidence, extract_ean, extract_detail_metadata
from scripts.scrapers.usf.jobs.refresh_soundsvenlo_listing_prices import fetch_listing_html

URL = 'https://www.sounds-venlo.nl/4818633-america-holiday-harmony/'


def product(content):
    return '<main><section><div><hgroup><h1>Holiday Harmony</h1></hgroup>' + content + '</div></section></main>'


class SoundsVenloTests(unittest.TestCase):
    def test_related_album_image_cannot_supply_missing_product_ean(self):
        html = product('<p>LP</p><p>Release 31-12-2026</p><p>4707526</p>')
        html += '<aside><a href="/4704205-fresku-in-het-diepe/">In Het Diepe</a>'
        html += '<img src="/images/0602475004783-1.jpg" alt="0602475004783-1"></aside>'
        proof = ean_evidence(html, 'https://www.sounds-venlo.nl/4707526-fresku-leren-leven/')
        self.assertIsNone(proof['ean'])
        self.assertEqual(proof['issue'], 'missing_valid_product_ean')

    def test_own_metadata_barcode_is_used(self):
        html = product('<p>LP</p><p>0792755872161</p><p>Release</p><p>07-11-2026</p>')
        self.assertEqual(extract_ean(html, URL), '00792755872161')
        self.assertEqual(extract_detail_metadata(html)['release_date'], '07-11-2026')

    def test_internal_product_id_and_invalid_checksum_are_rejected(self):
        self.assertIsNone(extract_ean(product('<p>4818633</p>'), URL))
        self.assertIsNone(extract_ean(product('<p>0792755872162</p>'), URL))

    def test_ambiguous_product_codes_are_not_chosen_arbitrarily(self):
        proof = ean_evidence(product('<p>0792755872161</p><p>0602475004783</p>'), URL)
        self.assertIsNone(proof['ean'])
        self.assertEqual(proof['issue'], 'ambiguous_product_eans')

    def test_structured_gtin_must_belong_to_current_product(self):
        related = {'@type': 'Product', 'url': 'https://www.sounds-venlo.nl/other/', 'gtin13': '0602475004783'}
        html = product('<p>4818633</p>') + '<script type="application/ld+json">' + json.dumps({'@graph': [related]}) + '</script>'
        self.assertIsNone(extract_ean(html, URL))
        own = {**related, 'url': URL, 'gtin13': '0792755872161'}
        html = product('<p>4818633</p>') + '<script type="application/ld+json">' + json.dumps({'@graph': [own, related]}) + '</script>'
        self.assertEqual(extract_ean(html, URL), '00792755872161')

    def test_origin_is_venlo_and_ten_second_pacing_is_preserved(self):
        self.assertEqual(canonical_url('https://sounds-venlo.nl/vinyl/'), 'https://www.sounds-venlo.nl/vinyl/')
        with self.assertRaises(ValueError):
            canonical_url('https://www.northendhaarlem.nl/')
        sleep = Mock()
        response = Mock(status_code=200, url=URL, headers={})
        with SoundsVenloSession(clock=Mock(side_effect=[0, 4, 10]), sleeper=sleep) as session, \
             patch('requests.Session.get', return_value=response) as get:
            session.get(URL)
            session.get(URL)
            sleep.assert_called_once_with(6)
            self.assertEqual(get.call_count, 2)

    def test_blocked_listing_is_not_retried_in_a_fresh_browser(self):
        blocked = requests.Response()
        blocked.status_code, blocked.url = 429, URL
        with SoundsVenloSession(sleeper=Mock()) as session, \
             patch('requests.Session.get', return_value=blocked) as get:
            with self.assertRaises(requests.HTTPError):
                fetch_listing_html(session, 'https://www.sounds-venlo.nl/vinyl/')
            session.get(URL)
            get.assert_called_once()

    def test_metadata_is_scoped_and_missing_label_is_not_guessed(self):
        html = product('<a href="/artiest-fresku">Fresku</a><a href="/hiphop-2/">Hiphop</a>'
                       '<a href="/lp/">LP</a><p>Release 31-12-2026</p><p>4707526</p>')
        html += '<aside>Release 01-01-2000</aside>'
        metadata = extract_detail_metadata(html)
        self.assertEqual(metadata['genre'], 'Hiphop')
        self.assertEqual(metadata['format'], 'LP')
        self.assertEqual(metadata['release_date'], '31-12-2026')
        self.assertEqual(metadata['detail_product_id'], '4707526')
        self.assertIsNone(metadata['label'])


if __name__ == '__main__':
    unittest.main()
