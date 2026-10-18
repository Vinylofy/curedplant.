import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.workers.approved_price_source import load_approved_source
from scripts.workers.run_catalog_price import main


class ApprovedPriceSourceTests(unittest.TestCase):
    def fixture(self, directory, **changes):
        now = datetime.now(timezone.utc)
        summary = dict(worker='suburban', run_id='1234', limit=0, write=False,
                       database_writes=0, status='green', source_returncode=0,
                       errors=[], started_at=(now-timedelta(minutes=10)).isoformat())
        summary.update(changes)
        root = Path(directory) / 'suburban'
        root.mkdir(parents=True, exist_ok=True)
        (root/'summary.json').write_text(json.dumps(summary))
        (root/'listing-records.jsonl').write_text(json.dumps(dict(source_url='https://suburban.nl/product/test', price='24.95', currency='EUR'))+'\n')
        return summary

    def test_replay_requires_matching_successful_read_only_evidence(self):
        for invalid in [dict(worker='different'),dict(run_id='999'),dict(write=True),
                        dict(database_writes=1),dict(status='red'),dict(source_returncode=1),
                        dict(errors=[{'reason':'failed'}]),dict(limit=1),
                        dict(started_at=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat())]:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                self.fixture(directory, **invalid)
                with self.assertRaises(ValueError):
                    load_approved_source(directory, 'suburban', 0, '1234')

    def test_write_uses_exact_reviewed_rows_without_a_second_shop_request(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'approved'
            previous = self.fixture(source)
            argv=['worker','--worker','suburban','--limit','0','--write',
                  '--approved-source-dir',str(source),'--approved-source-run','1234']
            with patch('sys.argv', argv), \
                 patch('scripts.workers.run_catalog_price.Path', side_effect=lambda p: Path(directory)/p), \
                 patch('scripts.workers.run_catalog_price.subprocess.run', side_effect=AssertionError('shop request forbidden')), \
                 patch('scripts.workers.price_database.update_existing', return_value={'updated':1,'verified':1}) as writer, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            self.assertEqual(str(writer.call_args.args[1][0]['price']), '24.95')
            self.assertEqual(writer.call_args.args[2].isoformat(), previous['started_at'])
            summary=json.loads((Path(directory)/'output/price-verification/suburban/summary.json').read_text())
            self.assertEqual((summary['approved_source_run'],summary['database_writes']),('1234',1))

    def test_failed_write_does_not_falsely_claim_zero_committed_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'approved'
            self.fixture(source)
            argv=['worker','--worker','suburban','--limit','0','--write',
                  '--approved-source-dir',str(source),'--approved-source-run','1234']
            with patch('sys.argv',argv), \
                 patch('scripts.workers.run_catalog_price.Path', side_effect=lambda p: Path(directory)/p), \
                 patch('scripts.workers.price_database.update_existing', side_effect=RuntimeError('post-commit check unavailable')), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(),1)
            summary=json.loads((Path(directory)/'output/price-verification/suburban/summary.json').read_text())
            self.assertIsNone(summary['database_writes'])
            self.assertEqual(summary['status'],'red')
