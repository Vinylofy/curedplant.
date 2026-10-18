import unittest
from unittest.mock import patch

from scripts.workers.ean_progress import GitHubProgress, initial_state, MAX_SAVE_ATTEMPTS


class CheckpointConflictTests(unittest.TestCase):
    def test_other_shops_branch_conflicts_retry_longer_than_old_three_attempts(self):
        store = GitHubProgress('rockinoutrecords')
        store.sha = 'unchanged-own-file'
        attempts = []
        def api(method, path, payload=None):
            self.assertEqual(method, 'PUT')
            attempts.append(payload)
            if len(attempts) < MAX_SAVE_ATTEMPTS:
                raise RuntimeError('gh: branch moved while updating another shop (HTTP 409)')
            return {'content': {'sha': 'saved'}}
        with patch.object(store, '_api', side_effect=api), patch.object(store, 'load', return_value=initial_state('rockinoutrecords')), patch('scripts.workers.ean_progress.time.sleep') as wait:
            store.save(initial_state('rockinoutrecords'))
        self.assertEqual(len(attempts), MAX_SAVE_ATTEMPTS)
        self.assertEqual(wait.call_count, MAX_SAVE_ATTEMPTS-1)
        self.assertEqual(store.sha, 'saved')
        self.assertTrue(all(1 <= call.args[0] <= 8 for call in wait.call_args_list))

    def test_same_shop_conflict_blocks_followup_finally_write(self):
        store = GitHubProgress('rockinoutrecords')
        store.sha = 'old-own-file'
        def load():
            store.sha = 'changed-own-file'
            return initial_state('rockinoutrecords')
        with patch.object(store, '_api', side_effect=RuntimeError('HTTP 409')) as api, patch.object(store, 'load', side_effect=load):
            with self.assertRaisesRegex(RuntimeError, 'Another run changed'):
                store.save(initial_state('rockinoutrecords'))
            with self.assertRaisesRegex(RuntimeError, 'stale state'):
                store.save(initial_state('rockinoutrecords'))
            self.assertEqual(api.call_count, 1)

    def test_non_conflict_error_is_not_retried(self):
        store = GitHubProgress('rockinoutrecords')
        with patch.object(store, '_api', side_effect=RuntimeError('HTTP 403')) as api:
            with self.assertRaises(RuntimeError): store.save(initial_state('rockinoutrecords'))
            self.assertEqual(api.call_count, 1)
