import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.workers import jpc_price_source as source


class Process:
    def __init__(self, code=0):
        self.returncode = code
    def poll(self):
        return self.returncode
    def wait(self, **kwargs):
        return self.returncode


class JpcPriceSourceTests(unittest.TestCase):
    def test_four_native_price_shards_cover_all_page_residues_without_writes(self):
        for index in range(4):
            command = source.command_for(index,0)
            self.assertIn('scripts.scrapers.usf.jobs.discover_jpc_vinyl', command)
            self.assertNotIn('--write',command)
            self.assertEqual(command[command.index('--listing-page-shard-index')+1],str(index))
            self.assertEqual(command[command.index('--listing-page-shard-count')+1],'4')
            self.assertEqual(command[command.index('--max-pages-per-route')+1],'0')

    def test_combines_all_four_read_only_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'records.jsonl'
            target.write_text('')
            def spawn(command, **kwargs):
                self.assertEqual(kwargs['env']['DATABASE_URL'],'')
                index=command[command.index('--listing-page-shard-index')+1]
                Path(kwargs['env']['CUREDPLANT_PRICE_EVIDENCE']).write_text(json.dumps({'source_url':f'https://jpc.de/hnum/{index}','price':'24.99'})+'\n')
                return Process()
            with patch.dict(os.environ,{'CUREDPLANT_PRICE_EVIDENCE':str(target),'DATABASE_URL':'never-pass-this'}), \
                 patch.object(source.subprocess,'Popen',side_effect=spawn), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(source.run(0),0)
            self.assertEqual(len(target.read_text().splitlines()),4)

    def test_a_failed_shard_cannot_yield_a_partial_green(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'records.jsonl'
            target.write_text('')
            with patch.dict(os.environ,{'CUREDPLANT_PRICE_EVIDENCE':str(target)}), \
                 patch.object(source.subprocess,'Popen',side_effect=[Process(0),Process(1),Process(0),Process(0)]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(source.run(0),1)
            records=[json.loads(line) for line in target.read_text().splitlines()]
            self.assertEqual(records[-1]['kind'],'source_error')

    def test_429_and_access_denials_stop_all_parts(self):
        self.assertIsNotNone(source.blocked_log('[JPC-DISCOVER-RATE-LIMIT] blocked'))
        self.assertIsNotNone(source.blocked_log("[JPC-DISCOVER-HTTP-SKIP] {'status_code': 403}"))
        self.assertIsNone(source.blocked_log("[JPC-DISCOVER-HTTP-SKIP] {'status_code': 404}"))
