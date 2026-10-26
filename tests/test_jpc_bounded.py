from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.workers import jpc_bounded_prices as cycle
from scripts.workers import jpc_bounded_source as source


class Store:
    def __init__(self, state=None):
        self.state = deepcopy(state)
        self.saved = []
    def load(self):
        return deepcopy(self.state)
    def save(self, state):
        self.state = deepcopy(state)
        self.saved.append(deepcopy(state))


def page(number, terminal=False):
    return {'signature': str(number), 'terminal': terminal, 'source_products': 20,
            'rows': [] if terminal else [{'source_url': f'https://www.jpc.de/jpcng/poprock/detail/-/art/lp/hnum/{number}',
                 'price': str(20+number%10), 'currency': 'EUR', 'availability': 'in_stock'}]}


class BoundedCycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.routes = [{'name': 'rock', 'url': 'https://www.jpc.de/s/1238692_66733?searchtype=cid'}]
        self.store = Store(cycle.new_state(self.routes))
        self.writer = Mock(return_value={'updated': 1, 'verified': 1})

    def run_cycle(self, fetch, **kwargs):
        return cycle.run(fetch, self.store, self.path, delay=0, writer=self.writer, **kwargs)

    def test_each_portion_publishes_and_next_run_resumes_exact_page(self):
        fetch = Mock(side_effect=[page(i) for i in range(1, 5)])
        result = self.run_cycle(fetch, write=True, page_limit=4, batch_size=2)
        self.assertEqual(result['database_updates'], 2)
        self.assertEqual(self.store.state['page'], 5)
        self.assertEqual([s['page'] for s in self.store.saved], [3, 5])
        next_fetch = Mock(return_value=page(5))
        self.run_cycle(next_fetch, write=True, page_limit=1)
        self.assertEqual(next_fetch.call_args.args[0]['page'], 5)
        self.assertEqual(len(list((self.path/'pages').glob('*.json'))), 4)

    def test_source_failure_preserves_completed_prices_and_retries_failed_page(self):
        fetch = Mock(side_effect=[page(1), page(2), RuntimeError('503')])
        result = self.run_cycle(fetch, write=True, page_limit=5)
        self.assertEqual(result['status'], 'partial_source_failure')
        self.assertEqual(result['database_updates'], 1)
        self.assertFalse(result['continue_cycle'])
        self.assertEqual(self.store.state['page'], 3)
        self.assertEqual(self.store.state['failure']['cursor'], [0, 3])
        self.writer.assert_called_once()

    def test_database_failure_never_advances_durable_cursor(self):
        self.writer.side_effect = RuntimeError('database unavailable')
        with self.assertRaises(RuntimeError):
            self.run_cycle(Mock(return_value=page(1)), write=True, page_limit=1)
        self.assertEqual(self.store.state['page'], 1)
        self.assertEqual(len(list((self.path/'pages').glob('*.json'))), 1)

    def test_failed_post_commit_readback_does_not_advance_cursor(self):
        self.writer.return_value = {'updated': 2, 'verified': 1}
        with self.assertRaises(ValueError):
            self.run_cycle(Mock(return_value=page(1)), write=True, page_limit=1)
        self.assertEqual(self.store.state['page'], 1)

    def test_checkpoint_failure_after_commit_replays_at_most_one_portion(self):
        self.store.save = Mock(side_effect=RuntimeError('CAS conflict'))
        with self.assertRaises(RuntimeError):
            self.run_cycle(Mock(side_effect=[page(1), page(2)]), write=True, page_limit=2)
        self.writer.assert_called_once()
        self.assertEqual(self.store.state['page'], 1)

    def test_dry_run_never_writes_database_or_shared_cursor(self):
        result = self.run_cycle(Mock(return_value=page(1)), write=False, page_limit=1)
        self.writer.assert_not_called()
        self.assertFalse(self.store.saved)
        self.assertEqual(self.store.state['page'], 1)
        self.assertFalse(result['continue_cycle'])

    def test_repeated_page_ends_route_and_finishes_daily_cycle(self):
        result = self.run_cycle(Mock(side_effect=[page(1), page(1)]), write=True, page_limit=5)
        self.assertEqual(result['cycle']['phase'], 'complete')
        self.assertFalse(result['continue_cycle'])
        fetch = Mock()
        result = self.run_cycle(fetch, write=True, scheduled=True)
        self.assertEqual(result['status'], 'waiting_daily_cycle')
        fetch.assert_not_called()

    def test_failed_page_retry_is_cooled_down(self):
        self.run_cycle(Mock(side_effect=RuntimeError()), write=True, page_limit=1)
        fetch = Mock()
        result = self.run_cycle(fetch, write=True, scheduled=True)
        self.assertEqual(result['status'], 'waiting_retry')
        fetch.assert_not_called()

    def test_quality_failure_never_publishes_or_checkpoints(self):
        result = page(1)
        result['rows'][0]['price'] = 'shipping EUR 4.95'
        with self.assertRaises(ValueError):
            self.run_cycle(Mock(return_value=result), write=True, page_limit=1)
        self.writer.assert_not_called()
        self.assertEqual(self.store.state['page'], 1)

    def test_empty_eligible_listing_page_is_not_catalogue_end(self):
        result = page(1)
        result['rows'] = []
        outcome = self.run_cycle(Mock(return_value=result), write=True, page_limit=1)
        self.assertEqual(self.store.state['page'], 2)
        self.assertEqual(outcome['status'], 'checked_no_price_updates')
        self.writer.assert_not_called()

    @patch.object(cycle.subprocess, 'run')
    def test_source_subprocess_receives_no_database_or_github_credentials(self, run):
        def emit(command, **kwargs):
            self.assertEqual(kwargs['env']['DATABASE_URL'], '')
            self.assertEqual(kwargs['env']['GH_TOKEN'], '')
            self.assertEqual(kwargs['env']['GITHUB_TOKEN'], '')
            Path(command[-1]).write_text('{}')
        run.side_effect = emit
        with patch.dict('os.environ', {'DATABASE_URL': 'never-pass', 'GH_TOKEN': 'never-pass'}):
            cycle.Source(self.path)({'kind': 'index'})

    def test_http_503_source_page_cannot_be_treated_as_end(self):
        import requests
        response = requests.Response()
        response.status_code = 503
        with patch.object(source.native, 'build_session'), \
             patch.object(source.native, 'request_listing_page', return_value=response), \
             self.assertRaises(requests.HTTPError):
            source.collect({'kind': 'page', 'route': self.routes[0], 'page': 5})

    def test_cycle_that_finishes_next_day_does_not_skip_that_days_round(self):
        from datetime import timedelta
        fixed = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
        self.store.state['cycle_started'] = (fixed-timedelta(days=1)).isoformat()
        self.store.state['phase'] = 'complete'
        self.store.state['completed_at'] = fixed.isoformat()
        fetch = Mock(side_effect=[{'routes': self.routes}, page(1, terminal=True)])
        with patch.object(cycle, 'now', return_value=fixed):
            result = self.run_cycle(fetch, write=False, scheduled=True, page_limit=1)
        self.assertEqual(result['status'], 'dry_run_checked')
        self.assertEqual(fetch.call_count, 2)
