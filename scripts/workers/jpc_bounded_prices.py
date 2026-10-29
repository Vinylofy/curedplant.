"""Bounded, resumable JPC price cycle; publish verified portions independently."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.workers.price_evidence import assess
from scripts.workers.price_database import update_existing
from scripts.workers.jpc_checkpoint import GitHubCheckpoint

UTC = timezone.utc


def now():
    return datetime.now(UTC)


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as handle:
        json.dump(value, handle, ensure_ascii=False, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class Source:
    def __init__(self, directory):
        self.directory = directory

    def __call__(self, request):
        request_path, output = self.directory/'request.json', self.directory/'response.json'
        atomic_json(request_path, request)
        output.unlink(missing_ok=True)
        # Collection never gets a database credential, GitHub token or write flag.
        env = dict(os.environ, DATABASE_URL='', GH_TOKEN='', GITHUB_TOKEN='',
                   CUREDPLANT_PRICE_EVIDENCE='', CUREDPLANT_JPC_COOLDOWN='',
                   PGOPTIONS='-c default_transaction_read_only=on')
        subprocess.run([sys.executable, '-u', '-m', 'scripts.workers.jpc_bounded_source',
                        '--request', str(request_path), '--output', str(output)],
                       env=env, check=True, timeout=300)
        return json.loads(output.read_text())


def new_state(routes):
    if not routes:
        raise ValueError('Empty shared route snapshot')
    return {'version': 1, 'phase': 'active', 'cycle_started': now().isoformat(),
            'routes': routes, 'route_index': 0, 'page': 1, 'signatures': [],
            'totals': {'pages': 0, 'priced_observations': 0, 'database_updates': 0},
            'failure': None}


def advance(state, result):
    repeated = bool(result.get('signature') and result['signature'] in state['signatures'])
    terminal = result['terminal'] or repeated
    state['totals']['pages'] += 1
    if terminal:
        state['route_index'] += 1
        state['page'] = 1
        state['signatures'] = []
        if state['route_index'] == len(state['routes']):
            state['phase'] = 'complete'
            state['completed_at'] = now().isoformat()
    else:
        state['signatures'].append(result['signature'])
        state['page'] += 1
    return [] if terminal else result['rows']


def run(source, store, directory, *, write=False, page_limit=50, batch_size=10,
        seconds=600, scheduled=False, delay=4, writer=update_existing):
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'pages').mkdir(exist_ok=True)
    summary = {'status': 'running', 'write': write, 'pages': 0, 'priced_products': 0,
               'database_updates': 0, 'verified': 0, 'portions': [], 'continue_cycle': False}
    started = time.monotonic()
    state = store.load()
    if state and state.get('version') != 1:
        raise ValueError('Unsupported checkpoint version')
    if state and state['phase'] == 'complete':
        completed_day = datetime.fromisoformat(state['cycle_started']).date()
        if scheduled and (now() < datetime.fromisoformat(state['cycle_started'])+timedelta(hours=24)
                          or completed_day >= now().date() or (now().hour, now().minute) < (3, 17)):
            return dict(summary, status='waiting_daily_cycle')
        state = None
    if state is None:
        if scheduled and (now().hour, now().minute) < (3, 17):
            return dict(summary, status='waiting_daily_cycle')
        state = new_state(source({'kind': 'index'})['routes'])
        if write:
            store.save(state)
    failure = state.get('failure')
    if scheduled and failure and now() < datetime.fromisoformat(failure['retry_after']):
        return dict(summary, status='waiting_retry', retry_after=failure['retry_after'])
    state = deepcopy(state)
    rows, pending = [], 0
    observed_at = now()

    def publish():
        nonlocal rows, pending, observed_at
        if not pending:
            return
        portion = {'pages': pending, 'priced_products': 0, 'database_updates': 0, 'verified': 0}
        if rows:
            valid, quality = assess(rows)
            if quality['status'] != 'green':
                raise ValueError('Price validation failed; cursor retained')
            portion['priced_products'] = len(valid)
            if write:
                stats = writer('jpc', valid, observed_at, allow_no_matches=True)
                portion['database_updates'] = stats['updated']
                portion['verified'] = stats['verified']
                if stats['updated'] != stats['verified']:
                    raise ValueError('Committed price verification incomplete')
        state['totals']['priced_observations'] += portion['priced_products']
        state['totals']['database_updates'] += portion['database_updates']
        state['failure'] = None
        # Only verified completed portions move the durable cursor. A crash
        # between commit and checkpoint re-fetches at most this portion safely.
        if write:
            store.save(state)
        for key in ('priced_products', 'database_updates', 'verified'):
            summary[key] += portion[key]
        summary['portions'].append(portion)
        atomic_json(directory/'progress.json', state)
        print('[JPC-BOUNDED] published portion', json.dumps(portion), flush=True)
        rows, pending, observed_at = [], 0, now()

    error = None
    while state['phase'] == 'active' and summary['pages'] < page_limit:
        if time.monotonic() - started >= seconds:
            break
        request = {'kind': 'page', 'route': state['routes'][state['route_index']], 'page': state['page']}
        try:
            result = source(request)
        except Exception as exc:
            error = type(exc).__name__
            break
        # Every completed page has an fsynced journal in the run artifact.
        atomic_json(directory/'pages'/f"{summary['pages']+1:04d}.json", {'request': request, 'result': result})
        rows.extend(advance(state, result))
        pending += 1
        summary['pages'] += 1
        print('[JPC-BOUNDED] page', json.dumps({'route': request['route']['name'], 'page': request['page'],
              'products': len(result['rows']), 'run_pages': summary['pages']}), flush=True)
        if pending >= batch_size or state['phase'] == 'complete':
            publish()
        if state['phase'] == 'active' and summary['pages'] < page_limit:
            time.sleep(delay)
    publish()
    if error:
        previous = failure or {}
        same = previous.get('cursor') == [state['route_index'], state['page']]
        attempts = previous.get('consecutive', 0) + 1 if same else 1
        state['failure'] = {'cursor': [state['route_index'], state['page']], 'consecutive': attempts,
                            'reason': error, 'retry_after': (now()+timedelta(minutes=360 if attempts >= 3 else 30)).isoformat()}
        if write:
            store.save(state)
        summary.update(status='partial_source_failure', error=error)
    else:
        summary['status'] = ('dry_run_checked' if not write else
                             'prices_verified' if summary['database_updates'] else 'checked_no_price_updates')
        summary['continue_cycle'] = write and state['phase'] == 'active'
    summary['cycle'] = {k: state[k] for k in ('phase', 'route_index', 'page', 'totals', 'cycle_started')}
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--scheduled', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('Bounded page limit must be 1-100; full scans resume automatically')
    directory = Path('output/jpc-bounded')
    directory.mkdir(parents=True, exist_ok=True)
    summary = {'status': 'failed', 'continue_cycle': False, 'database_updates': None}
    try:
        config = json.loads(Path('config/jpc-price-cycle.json').read_text())
        enabled = config.get('enabled') is True
        resume_after = datetime.fromisoformat(config['resume_after']) if config.get('resume_after') else None
        if (args.scheduled or args.write) and resume_after and now() < resume_after:
            summary = {'status': 'waiting_source_rest', 'continue_cycle': False, 'database_updates': 0,
                       'resume_after': config['resume_after']}
        elif args.scheduled and not enabled:
            summary = {'status': 'automation_disabled', 'continue_cycle': False, 'database_updates': 0}
        else:
            summary = run(Source(directory), GitHubCheckpoint(), directory, write=args.write,
                          page_limit=args.limit, scheduled=args.scheduled)
    except Exception as exc:
        # Do not expose database connection strings or token-bearing exceptions.
        summary['error'] = type(exc).__name__
        if isinstance(exc, NameError):
            # NameError metadata contains no secret values or argument contents.
            summary['undefined_name'] = exc.name
            frame = exc.__traceback__
            while frame and frame.tb_next:
                frame = frame.tb_next
            if frame:
                summary['error_location'] = f"{Path(frame.tb_frame.f_code.co_filename).name}:{frame.tb_lineno}"
    if args.write and summary.get('cycle'):
        try:
            from scripts.workers.price_database import jpc_cycle_coverage
            summary['coverage'] = jpc_cycle_coverage(datetime.fromisoformat(summary['cycle']['cycle_started']))
        except Exception as exc:
            summary['coverage_unavailable'] = type(exc).__name__
    atomic_json(directory/'summary.json', summary)
    print('[JPC-BOUNDED] result', json.dumps(summary), flush=True)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            handle.write('continue_cycle='+str(summary.get('continue_cycle', False)).lower()+'\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
            handle.write('### JPC bounded price cycle\n\n```json\n'+json.dumps(summary, indent=2)+'\n```\n')
    return 1 if summary['status'] in {'failed', 'partial_source_failure'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
