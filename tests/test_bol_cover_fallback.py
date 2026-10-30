import copy
from collections import Counter
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from scripts.workers import bol_cover_fallback as bol


PRODUCT = {'id': '00000000-0000-0000-0000-000000000001', 'ean': '0889854344115',
           'gtin_normalized': '00889854344115', 'format_label': 'LP'}
RESPONSE = {'ean': '0889854344115', 'bolProductId': 9200000078958183,
    'specificationGroups': [{'title': 'Muziek', 'specifications': [
        {'name': 'Type uitvoering', 'key': 'Music Format', 'values': 'LP'}]}],
    'image': {'url': 'https://media.s-bol.com/example.jpg', 'mimeType': 'image/jpeg'}}
ENV = {'BOL_COVER_FALLBACK_ENABLED': 'true', 'BOL_API_CLIENT_ID': 'id', 'BOL_API_CLIENT_SECRET': 'secret'}


class MemoryConnection:
    """Transactional RPC boundary double; SQL semantics have a separate DB test."""
    def __init__(self, products):
        self.products = products
        self.done, self.candidates, self.calls = set(), set(), []
        self.commit = Mock()
        self.rollback = Mock()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        result = None
        if 'bol_cover_next' in sql:
            lane, write, seen = params
            result = next((p for p in self.products if p.get('lane', 'new') == lane
                           and p['id'] not in self.done and p['id'] not in seen), None)
        elif 'bol_cover_record' in sql:
            pid, evidence = params
            self.done.add(pid)
            evidence = json.loads(evidence)
            result = int(evidence['match_status'] == 'exact_variant' and pid not in self.candidates)
            if result:
                self.candidates.add(pid)
        elif 'bol_cover_counts' in sql:
            result = {'missing_covers': len(self.products), 'checked': len(self.done)}
        return Mock(fetchone=Mock(return_value=(result,)))


class MatchingTests(unittest.TestCase):
    def test_exact_gtin_match_is_technical_only(self):
        result = bol.validate(PRODUCT, RESPONSE)
        self.assertEqual(result['match_status'], 'exact_variant')
        self.assertFalse(result['publication_eligible'])
        self.assertEqual(result['rights_status'], 'unconfirmed')

    def test_invalid_missing_and_damaged_ean(self):
        for ean in (None, '', '0889854344116', 'EAN 0889854344115', '0000000000000'):
            with self.subTest(ean=ean):
                self.assertEqual(bol.validate(dict(PRODUCT, ean=ean), RESPONSE)['error_status'], 'invalid_ean')

    def test_ean_mismatch(self):
        self.assertEqual(bol.validate(PRODUCT, dict(RESPONSE, ean='0602567549499'))['error_status'], 'ean_mismatch')

    def test_canonical_identity_conflict(self):
        self.assertEqual(bol.validate(dict(PRODUCT, gtin_normalized='00602567549499'), RESPONSE)['error_status'], 'invalid_ean')

    def test_upc_and_ean_same_validated_identity(self):
        self.assertEqual(bol.gtin('889854344115'), bol.gtin(PRODUCT['ean']))

    def test_cd_mismatch_and_unknown_format(self):
        for label in ('CD', None, 'LP + CD', 'digital'):
            data = copy.deepcopy(RESPONSE)
            data['specificationGroups'][0]['specifications'][0]['values'] = label
            self.assertEqual(bol.validate(PRODUCT, data)['error_status'], 'format_mismatch_or_unknown')

    def test_edition_colour_packaging_require_agreement(self):
        for name in ('Editie', 'Kleur', 'Verpakking'):
            data = copy.deepcopy(RESPONSE)
            data['specificationGroups'][0]['specifications'].append({'name': name, 'values': 'limited red box'})
            self.assertEqual(bol.validate(PRODUCT, data)['error_status'], 'variant_review')
        self.assertEqual(bol.validate(dict(PRODUCT, format_label='LP red'), RESPONSE)['error_status'], 'variant_review')
        self.assertEqual(bol.validate(PRODUCT, dict(RESPONSE, title='Album limited red vinyl'))['error_status'], 'variant_review')

    def test_existing_cover(self):
        for key in ('cover_url', 'cover_source_url', 'cover_storage_path'):
            self.assertEqual(bol.validate(dict(PRODUCT, **{key: 'existing'}), RESPONSE)['error_status'], 'existing_cover')

    def test_missing_or_unsafe_image(self):
        for image in (None, {}, {'url': 'http://media.s-bol.com/x'},
                      {'url': 'https://media.s-bol.com.attacker.test/x'},
                      {'url': 'https://user@media.s-bol.com/x'}):
            self.assertEqual(bol.validate(PRODUCT, dict(RESPONSE, image=image))['error_status'], 'missing_image')

    def test_missing_id_and_wrong_market(self):
        self.assertEqual(bol.validate(PRODUCT, dict(RESPONSE, bolProductId=None))['error_status'], 'missing_product_reference')
        self.assertEqual(bol.validate(PRODUCT, dict(RESPONSE, countryCode='BE'))['error_status'], 'wrong_market')

    def test_conflicting_specifications_fail_closed(self):
        data = copy.deepcopy(RESPONSE)
        data['specificationGroups'][0]['specifications'].append({'name': 'Type uitvoering', 'values': 'CD'})
        with self.assertRaises(ValueError):
            bol.validate(PRODUCT, data)


class ClientTests(unittest.TestCase):
    def client(self):
        return bol.Client(Counter(), sleep=Mock(), clock=lambda: 100)

    @patch.object(bol, 'authenticate', return_value=('token', 300))
    @patch.object(bol, 'request_json', side_effect=[bol.ReviewError('catalog', 'timeout')]*3)
    def test_timeout_bounded_backoff(self, request, auth):
        client = self.client()
        with self.assertRaises(bol.ReviewError):
            client.lookup(PRODUCT['ean'])
        self.assertEqual(request.call_count, 3)
        self.assertEqual(auth.call_count, 1)
        self.assertIn(unittest.mock.call(2), client.sleep.call_args_list)
        self.assertIn(unittest.mock.call(4), client.sleep.call_args_list)

    @patch.object(bol, 'authenticate', return_value=('token', 300))
    def test_429_500_and_401_stop_without_blind_retry(self, auth):
        for status in (429, 500, 401):
            client = self.client()
            with patch.object(bol, 'request_json', side_effect=bol.ReviewError('catalog', 'http_error', status)) as request:
                with self.assertRaises(bol.ReviewError):
                    client.lookup(PRODUCT['ean'])
                self.assertEqual(request.call_count, 1)
            self.assertEqual(client.metrics['rate_limits'], int(status == 429))

    @patch.object(bol, 'authenticate', return_value=('token', 300))
    @patch.object(bol, 'request_json', return_value=RESPONSE)
    def test_official_endpoint_parameters_rate_and_token_reuse(self, request, auth):
        client = self.client()
        client.lookup(PRODUCT['ean'])
        client.lookup(PRODUCT['ean'])
        self.assertEqual(auth.call_count, 1)
        self.assertIn('include-image=true', request.call_args.args[0].full_url)
        self.assertIn('include-specifications=true', request.call_args.args[0].full_url)
        self.assertIn('country-code=NL', request.call_args.args[0].full_url)
        client.sleep.assert_called_with(4)


class RunTests(unittest.TestCase):
    def run_with(self, conn, **kwargs):
        client = Mock(lookup=Mock(return_value=RESPONSE))
        result = bol.run('private-dsn', connect=lambda *a, **k: conn, env=ENV,
                         client_factory=lambda metrics: client, **kwargs)
        return result, client

    def test_disabled_and_missing_credentials_make_no_connections(self):
        for env in ({}, {'BOL_COVER_FALLBACK_ENABLED': 'true'},
                    dict(ENV, BOL_COVER_PUBLICATION_ENABLED='true')):
            connect = Mock()
            result = bol.run('secret-dsn', env=env, connect=connect)
            connect.assert_not_called()
            self.assertEqual(result['metrics']['published'], 0)
            self.assertNotIn('secret-dsn', json.dumps(result))

    def test_dry_run_zero_writes_and_no_checkpoint(self):
        conn = MemoryConnection([PRODUCT])
        result, client = self.run_with(conn, limit=2)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['metrics']['candidates_accepted'], 1)
        self.assertEqual(result['metrics']['database_writes'], 0)
        self.assertEqual(conn.done, set())
        conn.commit.assert_not_called()
        self.assertTrue(any('read only' in sql for sql, _ in conn.calls))

    def test_idempotence_and_checkpoint_resume_across_runs(self):
        second = dict(PRODUCT, id='00000000-0000-0000-0000-000000000002')
        conn = MemoryConnection([PRODUCT, second])
        first, _ = self.run_with(conn, write=True, limit=1)
        resumed, _ = self.run_with(conn, write=True, limit=1)
        again, client = self.run_with(conn, write=True, limit=2)
        self.assertEqual(first['metrics']['candidates_registered'], 1)
        self.assertEqual(resumed['metrics']['candidates_registered'], 1)
        self.assertEqual(again['metrics']['candidates_registered'], 0)
        client.lookup.assert_not_called()
        self.assertEqual(len(conn.candidates), 2)

    def test_new_and_historical_budgets(self):
        historical = dict(PRODUCT, id='00000000-0000-0000-0000-000000000002', lane='historical')
        conn = MemoryConnection([PRODUCT, historical])
        result, client = self.run_with(conn, write=True, limit=2)
        self.assertEqual(result['metrics']['checked'], 2)

    def test_invalid_and_existing_do_not_lookup(self):
        for product in (dict(PRODUCT, ean=None), dict(PRODUCT, cover_url='existing'),
                        dict(PRODUCT, gtin_normalized='conflict')):
            result, client = self.run_with(MemoryConnection([product]), limit=2)
            client.lookup.assert_not_called()

    def test_negative_result_is_checkpointed(self):
        conn = MemoryConnection([dict(PRODUCT, ean=None)])
        result, _ = self.run_with(conn, write=True, limit=2)
        self.assertEqual(len(conn.done), 1)
        self.assertEqual(len(conn.candidates), 0)

    def test_api_failure_stops_run_and_checkpoint_has_backoff(self):
        conn = MemoryConnection([PRODUCT])
        client = Mock(lookup=Mock(side_effect=bol.ReviewError('catalog', 'http_error', 429)))
        result = bol.run('dsn', write=True, limit=2, connect=lambda *a, **k: conn,
                         env=ENV, client_factory=lambda metrics: client)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(len(conn.done), 1)
        self.assertEqual(result['metrics']['database_writes'], 1)


class ContractTests(unittest.TestCase):
    def test_sql_quarantines_and_uses_existing_queue(self):
        root = Path(__file__).resolve().parents[1]
        sql = (root/'supabase/migrations/20261030210000_bol_cover_fallback.sql').read_text()
        self.assertIn('for update of q skip locked', sql)
        self.assertIn("last_error_code='no_candidates'", sql)
        self.assertIn("candidate_status = 'rejected'", sql)
        self.assertIn('image_url is null', sql)
        self.assertIn('on conflict (product_id)', sql)
        self.assertNotIn('create table', sql.lower())
        self.assertNotIn('grant execute', sql.split('to bol_cover_worker;')[-1])

    def test_workflow_is_independent_and_flags_are_safe(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root/'.github/workflows/bol-cover-fallback.yml').read_text()
        self.assertIn('ubuntu-latest', workflow)
        self.assertIn('vinylofy-cover-pipeline', workflow)
        self.assertNotIn('Vinylofy/Vinylofy', workflow)
        self.assertNotIn('SERVICE_ROLE', workflow)
        self.assertIn("BOL_COVER_PUBLICATION_ENABLED || 'false'", workflow)


if __name__ == '__main__':
    unittest.main()
