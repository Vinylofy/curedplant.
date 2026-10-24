from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from scripts.workers.variaworld_identity import detail_gtin, enrich_identities, fallback_matches, PROOF_KIND
from scripts.workers.price_evidence import url_key

OLD = 'https://www.variaworld.nl/artikel/detail.php?at=9076318000'
NEW = 'https://www.variaworld.nl/artikel/detail.php?at=7002617000'
EAN = '0888072686212'
HTML = '<div class="detail_tekstblok"><div class="detail_artikeltekst">Drager: lp nieuw</div><div class="detail_artikeltekst">EAN: ' + EAN + '</div></div>'


def record(url=NEW):
    return {'source_url': url, 'price': '32.00', 'shop_domain': 'variaworld.nl', 'currency': 'EUR',
            'identity_proof': {'kind': PROOF_KIND, 'url_key': url_key(url), 'gtin': EAN, 'observed_at': datetime.now(timezone.utc).isoformat()}}


class VariaworldIdentityTests(unittest.TestCase):
    def test_product_metadata_only_and_strict_barcode(self):
        self.assertEqual(detail_gtin(HTML), '00888072686212')
        self.assertIsNone(detail_gtin('<aside>EAN: ' + EAN + '</aside>'))
        self.assertIsNone(detail_gtin(HTML.replace(EAN, '0888072686213')))
        self.assertIsNone(detail_gtin(HTML.replace('lp nieuw', 'cd nieuw')))
        self.assertIsNone(detail_gtin(HTML.replace('lp nieuw', 'lp nieuw bijna nieuw')))
        self.assertIsNone(detail_gtin(HTML + HTML.replace(EAN, '8719262039971')))

    def test_unique_gtin_replaces_old_article_but_direct_listing_wins(self):
        target = {'product_id': 'one', 'product_url': OLD, 'ean': EAN}
        candidate = record()
        self.assertEqual(fallback_matches([candidate], [target]), {'one': candidate})
        self.assertEqual(fallback_matches([record(), {'source_url': OLD}], [target]), {})
        self.assertEqual(fallback_matches([record(), record(NEW.replace('7002617000', '7002617001'))], [target]), {})
        self.assertEqual(fallback_matches([record()], [target, {**target, 'product_id': 'two'}]), {})

    def test_foreign_or_mismatched_proof_is_rejected(self):
        target = {'product_id': 'one', 'product_url': OLD, 'ean': EAN}
        forged = record()
        forged['source_url'] = 'https://other.invalid/artikel/detail.php?at=7002617000'
        self.assertEqual(fallback_matches([forged], [target]), {})
        forged = record()
        forged['identity_proof']['url_key'] = url_key(OLD)
        self.assertEqual(fallback_matches([forged], [target]), {})

    def test_checkpoint_resumes_without_repeating_verified_details_or_changing_price(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            session = Mock()
            session.get.return_value = Mock(status_code=200, text=HTML, url=NEW)
            first = [{'source_url': NEW, 'price': '32.00'}]
            stats = enrich_identities(first, [], budget=1, cache_path=path, session=session, sleeper=Mock())
            self.assertEqual((stats['verified'], stats['lookups']), (1, 1))
            second = [{'source_url': NEW, 'price': '31.00'}]
            stats = enrich_identities(second, [], budget=0, cache_path=path, session=session, sleeper=Mock())
            self.assertEqual((stats['verified'], stats['cache_hits']), (1, 1))
            session.get.assert_called_once()
            self.assertEqual(second[0]['price'], '31.00')


if __name__ == '__main__':
    unittest.main()
