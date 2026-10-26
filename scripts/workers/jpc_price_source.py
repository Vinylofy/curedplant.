"""Collect JPC's two paced page shards inside one read-only price job."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from scripts.workers.price_evidence import capture

SHARDS = 2


def command_for(index, limit):
    return [sys.executable, '-u', '-m', 'scripts.scrapers.usf.jobs.discover_jpc_vinyl',
            '--routes', 'default', '--include-route-index', '--max-pages-per-route', str(limit),
            '--listing-page-shard-index', str(index), '--listing-page-shard-count', str(SHARDS),
            '--pagination-fallback', 'ff', '--availability-filter', 'none', '--delay', '4.0']


def blocked_log(text):
    for line in text.splitlines():
        if '[JPC-DISCOVER-RATE-LIMIT]' in line:
            return 'JPC HTTP429; all price shards stopped'
        if '[JPC-DISCOVER-HTTP-SKIP]' in line:
            status = re.search(r"['\"]status_code['\"]\s*:\s*(\d+)", line)
            if status and int(status[1]) not in {404, 410}:
                return f'JPC HTTP{status[1]}; source collection incomplete'
        if '[JPC-DISCOVER-ERROR]' in line:
            return 'JPC network error; source collection incomplete'
    return None


def run(limit):
    target = Path(os.environ['CUREDPLANT_PRICE_EVIDENCE'])
    processes, logs = [], []
    reason = None
    with tempfile.TemporaryDirectory(prefix='curedplant-jpc-prices-') as temporary:
        records = [Path(temporary)/f'shard-{i}.jsonl' for i in range(SHARDS)]
        try:
            for index in range(SHARDS):
                records[index].write_text('')
                log = (target.parent/f'jpc-source-shard-{index}.log').open('w', encoding='utf-8')
                logs.append(log)
                env = dict(os.environ, DATABASE_URL='', CUREDPLANT_PRICE_EVIDENCE=str(records[index]),
                           CUREDPLANT_JPC_COOLDOWN=str(Path(temporary)/'cooldown'))
                processes.append(subprocess.Popen(command_for(index, limit), stdout=log, stderr=subprocess.STDOUT, env=env))
                print(f'[JPC-PRICE] started read-only page shard {index+1}/{SHARDS}', flush=True)
            last_report = 0
            while any(process.poll() is None for process in processes):
                for index, process in enumerate(processes):
                    text = (target.parent/f'jpc-source-shard-{index}.log').read_text(errors='replace')
                    reason = blocked_log(text)
                    if not reason and process.poll() not in (None, 0):
                        reason = f'JPC source shard {index} exited with {process.returncode}'
                    if reason:
                        break
                if reason:
                    break
                if time.monotonic()-last_report >= 30:
                    counts = [len(path.read_text().splitlines()) for path in records]
                    print('[JPC-PRICE] source progress', json.dumps({'records_by_shard':counts,
                          'finished_shards':sum(p.poll()==0 for p in processes),'database_writes':0}), flush=True)
                    last_report = time.monotonic()
                time.sleep(2)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for log in logs:
                log.close()
            # The final evidence still includes partial rows on failure. The
            # source error prevents validation/writes; no partial green run.
            with target.open('a', encoding='utf-8') as output:
                for path in records:
                    if path.exists():
                        output.write(path.read_text())
        if not reason:
            for index, process in enumerate(processes):
                reason = blocked_log((target.parent/f'jpc-source-shard-{index}.log').read_text(errors='replace'))
                if process.returncode or reason:
                    reason = reason or f'JPC shard {index} failed with {process.returncode}'
                    break
        if reason:
            capture({'kind':'source_error','reason':reason})
            print('[JPC-PRICE] stopped:', reason, flush=True)
            return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('limit cannot be negative')
    return run(args.limit)


if __name__ == '__main__':
    raise SystemExit(main())
