import json
import unittest
from unittest.mock import patch
from scripts.importers import bol_api_review as api


class ApiReviewTests(unittest.TestCase):
    def setUp(self):
        probes = patch.object(api, 'EANS', api.EANS[:3])
        probes.start()
        self.addCleanup(probes.stop)

    def test_one_token_reused_for_six_requests_and_response_values_not_exported(self):
        requests = []
        def fetch(request, stage):
            requests.append(request)
            if stage == 'authentication':
                return {'access_token': 'private-token'}
            return {'ean': 'public-ean', 'offer': {'price': 24.95}, 'debug': 'private-value'}
        with patch.object(api, 'request_json', side_effect=fetch), patch.object(api.time, 'sleep'):
            result = api.review('private-id', 'private-secret')
        self.assertEqual(result['status'], 'review')
        self.assertEqual(result['database_writes'], 0)
        self.assertEqual(result['token_requests'], 1)
        self.assertEqual(len(requests), 7)
        self.assertTrue(all(r.get_header('Authorization') == 'Bearer private-token' for r in requests[1:]))
        self.assertIn('country-code=BE', requests[-1].full_url)
        self.assertNotIn('private-', json.dumps(result))

    def test_authentication_failure_stops_without_retry_or_secret_disclosure(self):
        with patch.object(api, 'request_json', side_effect=api.ReviewError('authentication', 'http_error', 401)) as fetch:
            result = api.review('secret-id', 'secret-password')
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result['errors'][0]['http_status'], 401)
        self.assertEqual(result['products'], [])
        self.assertNotIn('secret-', json.dumps(result))

    def test_rate_limit_stops_without_reauthenticating(self):
        with patch.object(api, 'request_json', side_effect=[{'access_token': 'token'}, api.ReviewError('catalog', 'http_error', 429)]) as fetch:
            result = api.review('id', 'password')
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['errors'][0]['http_status'], 429)

    def test_missing_credentials_makes_no_requests(self):
        with patch.object(api, 'request_json') as fetch:
            result = api.review(None, None)
        fetch.assert_not_called()
        self.assertEqual(result['token_requests'], 0)

    def test_not_found_is_not_a_validated_product(self):
        with patch.object(api, 'request_json', side_effect=[{'access_token': 'token'}] + [api.ReviewError('catalog', 'http_error', 404)] * 6), patch.object(api.time, 'sleep'):
            result = api.review('id', 'secret')
        self.assertEqual(result['status'], 'no_matches')
        self.assertTrue(all(not p['found'] for p in result['products']))

    def test_redirects_cannot_forward_authorization(self):
        self.assertIsNone(api.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))
