from datetime import datetime, timedelta, timezone
import unittest
from scripts.workers.bol_price_chain import gate, finish
from scripts.workers.bol_price_watchdog import decide

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
CONFIG = {'enabled': True, 'interval_minutes': 30}


class ChainTests(unittest.TestCase):
    def gate(self, state, **kwargs):
        return gate(CONFIG, state, managed=True, automatic=True, current=NOW, **kwargs)

    def test_waits_until_half_hour_start_cadence(self):
        result = self.gate({'next_due_at': (NOW+timedelta(minutes=7)).isoformat()})
        self.assertFalse(result['ready'])
        self.assertEqual(result['wait_seconds'], 420)

    def test_disabled_or_halted_chain_cannot_be_restarted_by_cron(self):
        self.assertFalse(gate({'enabled': False}, {}, managed=True, automatic=True, current=NOW)['ready'])
        self.assertFalse(self.gate({'halted': True})['ready'])
        self.assertTrue(self.gate({'halted': True}, resume=True)['ready'])

    def test_manual_probe_never_waits_on_automation_circuit(self):
        self.assertTrue(gate({}, {'halted': True}, managed=False, automatic=False)['ready'])

    def test_invalid_far_future_due_time_cannot_create_infinite_wait(self):
        result = self.gate({'next_due_at': (NOW+timedelta(days=1)).isoformat()})
        self.assertFalse(result['ready'])
        self.assertEqual(result['wait_seconds'], 0)

    def outcome(self, report, previous=None, started=None):
        return finish(previous or {}, report, run_id=123, config=CONFIG,
                      started_at=(started or NOW-timedelta(minutes=29)).isoformat(), current=NOW)

    def test_success_schedules_next_start_not_30_minutes_after_finish(self):
        state, chain = self.outcome({'status': 'success', 'checked': 1500, 'database_writes': 1100})
        self.assertTrue(chain)
        self.assertEqual(state['next_due_at'], (NOW+timedelta(minutes=1)).isoformat())
        self.assertEqual(state['transient_failures'], 0)

    def test_slow_success_continues_immediately_without_overlap(self):
        state, chain = self.outcome({'status': 'success'}, started=NOW-timedelta(minutes=40))
        self.assertEqual(state['next_due_at'], NOW.isoformat())
        self.assertTrue(chain)

    def test_no_more_than_two_transient_batch_restarts(self):
        report = {'status': 'blocked', 'database_writes': 0,
                  'errors': [{'reason': 'http_error', 'http_status': 503}]}
        first, chain = self.outcome(report)
        self.assertTrue(chain)
        second, chain = self.outcome(report, first)
        self.assertTrue(chain)
        third, chain = self.outcome(report, second)
        self.assertFalse(chain)
        self.assertTrue(third['halted'])
        self.assertNotIn('next_due_at', third)

    def test_429_auth_schema_and_uncertain_database_stop_automatic_retries(self):
        errors = [{'http_status': 429}, {'http_status': 401}, {'http_status': 403},
                  {'reason': 'invalid_json'}, {'reason': 'database_or_local_validation_failed'}]
        for error in errors:
            with self.subTest(error=error):
                state, chain = self.outcome({'status': 'blocked', 'database_writes': 0, 'errors': [error]})
                self.assertFalse(chain)
                self.assertTrue(state['halted'])
        state, chain = self.outcome({'status': 'blocked', 'database_writes': None,
                         'errors': [{'reason': 'timeout'}]})
        self.assertFalse(chain)

    def test_success_without_an_offer_can_advance_instead_of_starving_catalogue(self):
        state, chain = self.outcome({'status': 'success', 'checked': 1500, 'database_writes': 0})
        self.assertTrue(chain)
        self.assertEqual(state['database_writes'], 0)


class WatchdogTests(unittest.TestCase):
    def test_active_and_queued_runs_prevent_duplicates(self):
        for status in ['queued', 'in_progress', 'waiting']:
            self.assertEqual(decide(CONFIG, {}, [{'status': status}], NOW), 'run_active_or_queued')

    def test_watchdog_cannot_reopen_a_circuit_breaker(self):
        self.assertEqual(decide(CONFIG, {'halted': True}, [], NOW), 'circuit_open')
        self.assertEqual(decide({'enabled': False}, {}, [], NOW), 'automation_disabled')

    def test_recent_success_is_not_a_stalled_chain(self):
        control = {'last_success_at': (NOW-timedelta(minutes=20)).isoformat()}
        self.assertEqual(decide(CONFIG, control, [], NOW), 'recent_success')

    def test_stalled_successful_chain_can_restart_at_saved_cursor(self):
        control = {'last_success_at': (NOW-timedelta(minutes=60)).isoformat()}
        self.assertEqual(decide(CONFIG, control, [], NOW), 'restart_stalled_chain')

    def test_unclassified_job_failure_needs_review_not_blind_restart(self):
        runs = [{'status': 'completed', 'conclusion': 'failure', 'id': 123}]
        self.assertEqual(decide(CONFIG, {}, runs, NOW), 'unclassified_failure_requires_review')

    def test_due_time_and_known_retry_budget_are_respected(self):
        state = {'status': 'transient_failure', 'last_run_id': '123',
                 'next_due_at': (NOW+timedelta(minutes=3)).isoformat()}
        runs = [{'status': 'completed', 'conclusion': 'failure', 'id': 123}]
        self.assertEqual(decide(CONFIG, state, runs, NOW), 'not_due')
        state['next_due_at'] = (NOW-timedelta(minutes=1)).isoformat()
        self.assertEqual(decide(CONFIG, state, runs, NOW), 'restart_stalled_chain')

class WriterHistoryTests(unittest.TestCase):
    def inspect(self, jobs):
        from scripts.workers.bol_price_watchdog import uncheckpointed_writer_failure
        runs = [{'id': 123, 'conclusion': 'cancelled'}, {'id': 100, 'conclusion': 'success'}]
        return uncheckpointed_writer_failure(runs, '100', lambda run_id: jobs)

    def test_cancelled_pending_run_with_no_jobs_never_blocks_chain(self):
        self.assertIsNone(self.inspect([]))

    def test_cancelled_gate_or_skipped_importer_never_blocks_chain(self):
        self.assertIsNone(self.inspect([{'name': 'cadence', 'steps': []},
            {'name': 'prices', 'steps': [{'name': 'Refresh verified NL offers', 'conclusion': 'skipped'}]}]))

    def test_actual_importer_cancelled_after_start_still_blocks(self):
        self.assertEqual(self.inspect([{'steps': [{'name': 'Refresh verified NL offers without product or cover creation',
                          'started_at': NOW.isoformat(), 'conclusion': 'cancelled'}]}]), 123)

    def test_green_noop_cannot_hide_earlier_uncheckpointed_writer(self):
        from scripts.workers.bol_price_watchdog import uncheckpointed_writer_failure
        runs = [{'id': 124, 'conclusion': 'success'}, {'id': 123, 'conclusion': 'failure'}]
        jobs = [{'steps': [{'name': 'Refresh verified NL offers', 'started_at': NOW.isoformat(), 'conclusion': 'failure'}]}]
        self.assertEqual(uncheckpointed_writer_failure(runs, '100', lambda _: jobs), 123)

    def test_recorded_failure_is_controlled_by_its_persisted_breaker(self):
        from scripts.workers.bol_price_watchdog import uncheckpointed_writer_failure
        self.assertIsNone(uncheckpointed_writer_failure([{'id': 123, 'conclusion': 'failure'}], '123',
                                                       lambda _: self.fail('Known outcome needs no inspection')))


if __name__ == '__main__':
    unittest.main()
