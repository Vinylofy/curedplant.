from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
import requests
from unittest.mock import Mock

from scripts.workers.variaworld_identity import detail_gtin, enrich_identities, fallback_matches, PROOF_KIND
from scripts.workers.price_evidence import url_key

OLD = 'https://www.variaworld.nl/artikel/detail.php?at=9076318000'
NEW = 'https://www.variaworld.nl/artikel/detail.php?at=7002617000'
EAN = '0888072686212'
HTML = '<div class="detail_tekst_container"><div class="detail_tekstblok"><div class="detail_artikeltekst">Drager: lp nieuw</div><div class="detail_artikeltekst">EAN: ' + EAN + '</div></div></div>'


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

    def test_transient_timeout_retries_same_identity_and_does_not_touch_price(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Mock()
            session.get.side_effect = [requests.Timeout('temporary'), Mock(status_code=200, text=HTML, url=NEW)]
            rows = [{'source_url': NEW, 'price': '32.00'}]
            stats = enrich_identities(rows, [], budget=1, cache_path=Path(directory) / 'cache.json', session=session, sleeper=Mock())
            self.assertEqual(stats['verified'], 1)
            self.assertEqual([call.args[0] for call in session.get.call_args_list], [NEW, NEW])
            self.assertEqual(rows[0]['price'], '32.00')

    def test_challenge_page_is_not_cached_as_missing_barcode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            session = Mock()
            session.get.return_value = Mock(status_code=200, text='<h1>Verify you are human</h1>', url=NEW)
            with self.assertRaisesRegex(RuntimeError, 'Blocked Variaworld'):
                enrich_identities([{'source_url': NEW}], [], budget=1, cache_path=path, session=session, sleeper=Mock())
            self.assertFalse(path.exists())

    def test_old_cache_proofs_require_reverification_after_parser_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cache.json'
            path.write_text(json.dumps({'version': 1, 'entries': {url_key(NEW):
                {'gtin': EAN, 'observed_at': datetime.now(timezone.utc).isoformat()}}}))
            rows = [{'source_url': NEW, 'price': '32.00'}]
            stats = enrich_identities(rows, [], budget=0, cache_path=path, session=Mock(), sleeper=Mock())
            self.assertEqual((stats['pending'], stats['cache_hits']), (1, 0))
            self.assertNotIn('identity_proof', rows[0])

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

class VariaworldOptionalIdentityTests(unittest.TestCase):
    def test_identity_timeout_does_not_stop_verified_listing_price_publication(self):
        import contextlib
        import io
        import os
        from unittest.mock import patch
        from scripts.workers import run_catalog_price as worker
        from scripts.workers.price_evidence import capture
        registered = {'product_id': 'existing', 'product_url': OLD, 'ean': EAN, 'gtin_normalized': EAN.zfill(14)}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(worker, 'Path', side_effect=lambda path: Path(directory) / path), \
             patch('psycopg.connect') as connect, \
             patch('scripts.workers.variaworld_identity.enrich_identities', side_effect=requests.Timeout('temporary')), \
             patch('scripts.workers.price_database.update_existing', return_value={'updated': 1, 'verified': 1}) as writer, \
             patch.dict(os.environ, {'DATABASE_URL': 'parent-only'}), \
             patch('sys.argv', ['worker', '--worker', 'variaworld', '--limit', '1', '--write']), \
             contextlib.redirect_stdout(io.StringIO()):
            connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = [registered]
            def collect(command, **kwargs):
                with patch.dict(os.environ, kwargs['env']):
                    capture({'source_url': OLD, 'price': '35.00', 'shop_domain': 'variaworld.nl'})
                    capture({'source_url': NEW, 'price': '32.00', 'shop_domain': 'variaworld.nl'})
                return Mock(returncode=0)
            with patch.object(worker.subprocess, 'run', side_effect=collect):
                self.assertEqual(worker.main(), 0)
            self.assertEqual(writer.call_count, 1)
            self.assertTrue(all(not row.get('identity_proof') for row in writer.call_args.args[1]))
            summary = json.loads((Path(directory) / 'output/price-verification/variaworld/summary.json').read_text())
            self.assertEqual(summary['identity_review']['status'], 'deferred')
            self.assertEqual(summary['identity_review']['pending'], 1)


if __name__ == '__main__':
    unittest.main()
