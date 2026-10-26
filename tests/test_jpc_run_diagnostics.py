import json
from pathlib import Path
import tempfile
import unittest

from scripts.workers.jpc_run_diagnostics import report


class DiagnosticsTests(unittest.TestCase):
    def test_partial_failure_is_reported_without_raw_errors_or_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'summary.json').write_text(json.dumps({
                'status': 'red', 'observations': 4000, 'priced_products': 3999,
                'source_returncode': 1, 'database_writes': 0,
                'errors': [{'error': 'secret-connection-string'}],
                'samples': [{'password': 'secret-password'}]}))
            (path / 'jpc-source-shard-0.log').write_text(
                "[JPC-DISCOVER-PAGE] {'page': 5, 'url': 'secret-url'}\n"
                "[JPC-DISCOVER-HTTP-SKIP] {'status_code': 503}\n"
                "[JPC-DISCOVER-ERROR] {'error': 'secret-exception'}\n"
                "[JPC-DISCOVER-RETRY] {'page': 5, 'attempt': 1}\n")
            value = report(path)
            self.assertEqual(value['database_writes'], 0)
            self.assertEqual(value['shards'][0]['pages'], 1)
            self.assertEqual(value['shards'][0]['last_page'], 5)
            self.assertEqual(value['shards'][0]['http_errors'], [503])
            self.assertTrue(value['shards'][0]['network_error'])
            self.assertEqual(value['shards'][0]['transient_retries'], 1)
            self.assertNotIn('secret', json.dumps(value))

    def test_no_summary_and_missing_logs_remain_explicitly_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            value = report(Path(directory))
            self.assertFalse(value['summary_available'])
            self.assertTrue(all(not shard['log_available'] for shard in value['shards']))
            self.assertNotIn('database_writes', value)
