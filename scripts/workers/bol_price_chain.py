"""Cadence and circuit breaker around the existing verified Bol NL importer."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import time

CONFIG = Path('config/bol-price-cycle.json')
CONTROL = Path('state/bol-api/automation.json')
CURSOR = Path('state/bol-api/nl.json')
OUTPUT = Path('output/bol-chain')
UTC = timezone.utc


def utcnow():
    return datetime.now(UTC)


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Cadence timestamps must include timezone')
    return result


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def blob_sha(path):
    if not path.exists():
        return None
    data = path.read_bytes()
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def gate(config, state, *, managed, automatic, resume=False, current=None):
    current = current or utcnow()
    if not managed:
        return {'ready': True, 'reason': 'manual_probe', 'wait_seconds': 0}
    if config.get('enabled') is not True:
        return {'ready': False, 'reason': 'automation_disabled', 'wait_seconds': 0}
    if state.get('halted') and not resume:
        return {'ready': False, 'reason': 'circuit_open', 'wait_seconds': 0}
    wait = 0
    if automatic and not resume and state.get('next_due_at'):
        wait = max(0, (stamp(state['next_due_at'])-current).total_seconds())
        if wait < 1:
            wait = 0
        if wait > 30*60+5:
            return {'ready': False, 'reason': 'invalid_future_due_time', 'wait_seconds': 0}
    return {'ready': wait == 0, 'reason': 'cadence_wait' if wait else 'due', 'wait_seconds': wait}


def finish(previous, report, *, run_id, started_at, config, resume=False, current=None):
    current = current or utcnow()
    interval = config.get('interval_minutes', 30)
    if interval != 30:
        raise ValueError('Bol chain cadence must remain 30 minutes')
    result = dict(previous, version=1, country='NL', last_run_id=str(run_id),
                  last_finished_at=current.isoformat(), halted=False)
    success = report.get('status') == 'success'
    if success:
        result.pop('errors', None)
        result.update(transient_failures=0, status='success',
                      last_success_at=current.isoformat(), last_started_at=started_at,
                      checked=report.get('checked', 0), database_writes=report.get('database_writes'),
                      next_due_at=max(current, stamp(started_at)+timedelta(minutes=interval)).isoformat())
        return result, True
    errors = report.get('errors') or []
    transient = bool(errors) and all(
        error.get('http_status') in {500, 502, 503, 504} or
        (error.get('http_status') is None and error.get('reason') in {'timeout', 'connection_failed'})
        for error in errors)
    # A failed post-commit verification is not a safe automatic retry.
    if report.get('database_writes') is None:
        transient = False
    count = (0 if resume else previous.get('transient_failures', 0))+1
    result.update(status='transient_failure' if transient else 'blocked', transient_failures=count,
                  errors=[{key: e.get(key) for key in ('stage', 'reason', 'http_status')} for e in errors[:5]])
    if transient and count <= 2:
        result['next_due_at'] = (current+timedelta(minutes=5)).isoformat()
        return result, True
    result.update(halted=True, status='blocked')
    result.pop('next_due_at', None)
    return result, False


def output(values):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT/'decision.json').write_text(json.dumps(values, indent=2)+'\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            for key, value in values.items():
                if isinstance(value, bool):
                    value = str(value).lower()
                if isinstance(value, (str, int, float)):
                    handle.write(f'{key}={value}\n')
    print('[BOL-CHAIN]', json.dumps(values), flush=True)


def mode():
    managed = os.environ.get('BOL_CHAIN_WRITE') == 'true' and os.environ.get('BOL_CHAIN_SAMPLE') != 'true'
    automatic = os.environ.get('BOL_CHAIN_AUTOMATIC') == 'true'
    resume = os.environ.get('BOL_CHAIN_RESUME') == 'true'
    return managed, automatic, resume


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('gate', 'history', 'begin', 'finish'))
    parser.add_argument('--wait', action='store_true')
    args = parser.parse_args()
    config, state = read(CONFIG, {}), read(CONTROL, {})
    if state and (state.get('version') != 1 or state.get('country') != 'NL'):
        raise ValueError('Unexpected Bol automation state')
    managed, automatic, resume = mode()
    if args.phase == 'history':
        if not managed or resume:
            output({'safe': True})
            return
        from scripts.workers.bol_price_watchdog import gh_api, uncheckpointed_writer_failure, REPO
        runs = gh_api('repos/'+REPO+'/actions/workflows/price-bol-api.yml/runs?status=completed&per_page=50')['workflow_runs']
        runs = [r for r in runs if str(r['id']) != os.environ.get('GITHUB_RUN_ID')
                and r.get('head_branch') == 'main' and 'write=false' not in r.get('display_title', '')
                and 'sample=true' not in r.get('display_title', '')]
        failed = uncheckpointed_writer_failure(runs, state.get('last_run_id'),
            lambda run_id: gh_api('repos/'+REPO+'/actions/runs/'+str(run_id)+'/jobs')['jobs'])
        output({'safe': failed is None})
        if failed is not None:
            print('::warning::Previous importer started but its writer outcome was not checkpointed; investigate and explicitly resume.')
        return
    if args.phase == 'gate':
        decision = gate(config, state, managed=managed, automatic=automatic, resume=resume)
        if args.wait and decision['wait_seconds']:
            until = time.monotonic()+decision['wait_seconds']
            print('[BOL-CHAIN] waiting until next batch is due', json.dumps(decision), flush=True)
            while time.monotonic() < until:
                time.sleep(min(30, max(0, until-time.monotonic())))
            decision = gate(config, state, managed=managed, automatic=automatic, resume=resume)
        output(decision)
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.phase == 'begin':
        (OUTPUT/'baseline.json').write_text(json.dumps({'cursor_sha': blob_sha(CURSOR),
            'automation_sha': blob_sha(CONTROL), 'started_at': utcnow().isoformat()}))
        return
    if not managed:
        output({'continue_chain': False, 'publish_cursor': False, 'publish_control': False})
        return
    report = read(Path('output/bol-api-prices/review.json'),
                  {'status': 'failed', 'errors': [{'reason': 'missing_importer_report'}], 'database_writes': None})
    baseline = read(OUTPUT/'baseline.json')
    next_state, should_continue = finish(state, report, run_id=os.environ['GITHUB_RUN_ID'],
        started_at=baseline['started_at'], config=config, resume=resume)
    (OUTPUT/'automation.json').write_text(json.dumps(next_state, indent=2)+'\n')
    output({'continue_chain': should_continue and automatic,
            'publish_cursor': report.get('status') == 'success', 'publish_control': True,
            'status': next_state['status'], 'halted': next_state['halted']})


if __name__ == '__main__':
    main()
