"""Local Windows safety net. Uses existing gh authentication, never stores a token."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

REPO = 'Vinylofy/curedplant.'
WORKFLOW = 'price-bol-api.yml'


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp has no timezone')
    return result


def decide(config, control, runs, now):
    if config.get('enabled') is not True:
        return 'automation_disabled'
    if control.get('halted'):
        return 'circuit_open'
    if any(r['status'] in {'queued', 'in_progress', 'requested', 'waiting', 'pending'} for r in runs):
        return 'run_active_or_queued'
    if control.get('next_due_at') and now < stamp(control['next_due_at']):
        return 'not_due'
    if control.get('status') == 'blocked':
        return 'blocked'
    if runs and runs[0].get('conclusion') in {'failure', 'cancelled', 'timed_out'}:
        if str(runs[0]['id']) != control.get('last_run_id') or control.get('status') != 'transient_failure':
            return 'unclassified_failure_requires_review'
    last_success = control.get('last_success_at')
    if not last_success:
        successful = next((r for r in runs if r.get('conclusion') == 'success'), None)
        last_success = successful.get('updated_at') if successful else None
    if last_success and (now-stamp(last_success)).total_seconds() < 45*60:
        return 'recent_success'
    return 'restart_stalled_chain'


def uncheckpointed_writer_failure(runs, known_run_id, jobs_for):
    """Queued/gate-only cancellations made no API or database calls."""
    for run in runs:
        if str(run['id']) == known_run_id:
            break
        if run.get('conclusion') not in {'failure', 'cancelled', 'timed_out'}:
            continue
        jobs = jobs_for(run['id'])
        attempted = any(step.get('started_at') and step.get('conclusion') != 'skipped'
            and step.get('name', '').startswith('Refresh verified NL offers')
            for job in jobs for step in job.get('steps', []))
        if attempted:
            return run['id']
    return None


def gh_api(path, payload=None):
    command = ['gh', 'api', '--method', 'POST' if payload is not None else 'GET', path]
    if payload is not None:
        command += ['--input', '-']
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('GitHub authentication/API request failed; no repeated dispatch')
    return json.loads(result.stdout) if result.stdout.strip() else None


def content(path, optional=False):
    # Query only fixed paths, never a token/secret file.
    try:
        data = gh_api('repos/'+REPO+'/contents/'+path+'?ref=main')
    except RuntimeError:
        if optional:
            # An unavailable control file is not permission to ignore a breaker.
            raise RuntimeError('Automation state unavailable; refusing automatic restart')
        raise
    if data.get('encoding') != 'base64':
        raise ValueError('Unexpected GitHub content encoding')
    return json.loads(base64.b64decode(data['content']))


def run(dispatch=False):
    # Normal gh credential selection under the scheduled task's own identity.
    auth = subprocess.run(['gh', 'auth', 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if auth.returncode:
        raise RuntimeError('Configure GitHub CLI authentication locally for the task account')
    config = content('config/bol-price-cycle.json')
    if config.get('enabled') is not True:
        return {'decision': 'automation_disabled', 'dispatched': False}
    control = content('state/bol-api/automation.json')
    runs = gh_api('repos/'+REPO+'/actions/workflows/'+WORKFLOW+'/runs?per_page=20')['workflow_runs']
    relevant = [r for r in runs if r.get('head_branch') == 'main'
                and 'write=false' not in r.get('display_title', '') and 'sample=true' not in r.get('display_title', '')]
    unknown = uncheckpointed_writer_failure(relevant, control.get('last_run_id'),
        lambda run_id: gh_api('repos/'+REPO+'/actions/runs/'+str(run_id)+'/jobs')['jobs'])
    if unknown:
        return {'decision': 'unclassified_failure_requires_review', 'dispatched': False}
    # Empty/gate-only cancelled runs have been proven harmless above.
    effective_runs = [r for r in runs if r.get('conclusion') not in {'cancelled', 'failure', 'timed_out'}
                      or str(r['id']) == control.get('last_run_id')]
    decision = decide(config, control, effective_runs, datetime.now(timezone.utc))
    if decision == 'restart_stalled_chain' and dispatch:
        gh_api('repos/'+REPO+'/actions/workflows/'+WORKFLOW+'/dispatches',
               {'ref': 'main', 'inputs': {'limit': '1500', 'sample': 'false', 'write': 'true',
                                         'continue_chain': 'true', 'resume_chain': 'false'}})
    return {'decision': decision, 'dispatched': decision == 'restart_stalled_chain' and dispatch}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dispatch', action='store_true', help='Restart only a stalled, permitted chain')
    parser.add_argument('--result-file', type=Path)
    args = parser.parse_args()
    try:
        result = run(args.dispatch)
    except (RuntimeError, ValueError, OSError):
        print(json.dumps({'decision': 'local_auth_or_api_setup_required', 'dispatched': False}))
        raise SystemExit(1)
    result['checked_at'] = datetime.now(timezone.utc).isoformat()
    if args.result_file:
        args.result_file.write_text(json.dumps(result)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
