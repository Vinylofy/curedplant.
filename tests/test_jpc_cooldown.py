import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.workers import jpc_cooldown as cooldown


class CooldownTests(unittest.TestCase):
    def test_other_worker_obeys_pause_and_rechecks_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cooldown'
            path.write_text('160')
            clock = [100]
            sleeps = []
            def sleep(seconds):
                sleeps.append(seconds)
                clock[0] += seconds
                if len(sleeps) == 1:
                    # Another source process extends while this one sleeps.
                    path.write_text('180')
            with patch.dict(os.environ, {'CUREDPLANT_JPC_COOLDOWN': str(path)}), \
                 patch.object(cooldown.time, 'monotonic', side_effect=lambda: clock[0]), \
                 patch.object(cooldown.time, 'sleep', side_effect=sleep):
                cooldown.wait()
            self.assertEqual(sleeps, [60, 20])

    def test_new_pause_cannot_shorten_other_workers_existing_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cooldown'
            path.write_text('300')
            with patch.dict(os.environ, {'CUREDPLANT_JPC_COOLDOWN': str(path)}), \
                 patch.object(cooldown.time, 'monotonic', return_value=100), \
                 patch.object(cooldown, 'wait') as wait:
                cooldown.defer(60)
                self.assertEqual(float(path.read_text()), 300)
                wait.assert_called_once_with()

    def test_native_standalone_worker_has_no_linux_lock_dependency(self):
        with patch.dict(os.environ, {'CUREDPLANT_JPC_COOLDOWN': ''}), \
             patch.object(cooldown.time, 'sleep') as sleep, \
             patch.object(cooldown, 'deadline_file') as lock:
            cooldown.wait()
            cooldown.defer(60)
            sleep.assert_called_once_with(60)
            lock.assert_not_called()
