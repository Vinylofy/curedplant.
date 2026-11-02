"""Velvet Delft EAN budgets and durable public source checkpoints; no database access."""
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from scripts.scrapers.velvetdelft import DETAIL_REVISION, save

CHECKPOINT = 'state/velvetdelft/checkpoint.json.gz'


def initial_pending(row):
    return not row.get('detail_observed_at') or row.get('detail_parser_revision') != DETAIL_REVISION


def day(at=None):
    return (at or datetime.now(timezone.utc)).astimezone(ZoneInfo('Europe/Amsterdam')).date().isoformat()


def plan(state, at=None, extra_initial=False):
    today=day(at)
    ledger=state.setdefault('automation',{})
    if ledger.get('budget_day')!=today:
        ledger.update(budget_day=today,daily_checks=0)
    if extra_initial:
        pending=len(selected_rows(state,'extra_initial',1000000))
        return {'enabled':pending>0,'phase':'extra_initial','limit':min(1000,pending),'initial_remaining':pending,'reason':'explicit extra batch of never-enriched records; regular daily budget unchanged'}
    pending=sum(initial_pending(r) for r in state['records'].values())
    if pending:
        if ledger.get('phase')!='initial':ledger.pop('initial_completed_day',None)
        ledger['phase']='initial'
        limit=min(pending,max(0,1000-int(ledger.get('daily_checks',0))))
        return {'enabled':limit>0,'phase':'initial','limit':limit,'initial_remaining':pending,'reason':'daily initial EAN round' if limit else 'daily 1000-check budget already spent'}
    ledger['phase']='maintenance'
    ledger.setdefault('initial_completed_day',today)
    previous=ledger.get('last_maintenance_day') or ledger['initial_completed_day']
    weekly_due=(date.fromisoformat(today)-date.fromisoformat(previous)).days>=7
    if weekly_due and (not ledger.get('maintenance_window_day') or (ledger.get('last_maintenance_day') and ledger['last_maintenance_day']>=ledger['maintenance_window_day'])):
        ledger.update(maintenance_window_day=today,weekly_checks=0)
    limit=min(len(state['records']),max(0,250-int(ledger.get('weekly_checks',0))),max(0,1000-int(ledger.get('daily_checks',0)))) if weekly_due else 0
    return {'enabled':limit>0,'phase':'maintenance','limit':limit,'initial_remaining':0,'reason':'weekly oldest-record review' if limit else 'waiting for weekly maintenance date'}


def selected_rows(state, phase, limit):
    rows=list(state['records'].values())
    if phase=='initial':rows=[r for r in rows if initial_pending(r)]
    if phase=='extra_initial':rows=[r for r in rows if not r.get('detail_observed_at') and not (r.get('ean') or r.get('gtin14') or r.get('ean_status')=='verified')]
    # Oldest observation first makes weekly 250-record checks rotate.
    rows.sort(key=lambda r:(r.get('detail_observed_at',''),r['source_product_id']))
    return rows[:limit]


def attempt(state, at=None, extra_initial=False):
    ledger=state.setdefault('automation',{});today=day(at)
    if ledger.get('budget_day')!=today:ledger.update(budget_day=today,daily_checks=0)
    if extra_initial:
        ledger['extra_initial_checks']=int(ledger.get('extra_initial_checks',0))+1
        return
    if ledger.get('daily_checks',0)>=1000:raise ValueError('Daily EAN budget exhausted')
    ledger['daily_checks']=int(ledger.get('daily_checks',0))+1
    if ledger.get('phase')=='maintenance':ledger['weekly_checks']=int(ledger.get('weekly_checks',0))+1


def finish(state, phase, checks, error, at=None):
    ledger=state.setdefault('automation',{});today=day(at)
    ledger.update(last_run_day=today,last_run_checks=checks,last_run_error=error)
    if not any(initial_pending(r) for r in state['records'].values()):
        ledger.setdefault('initial_completed_day',today);ledger['phase']='maintenance'
    if phase=='maintenance' and checks and (not error or ledger.get('weekly_checks',0)>=250):ledger['last_maintenance_day']=today


def restore(path):
    target=Path(path);candidates=[]
    if target.exists():candidates.append(json.loads(target.read_text()))
    durable=Path(CHECKPOINT)
    if durable.exists():candidates.append(json.loads(gzip.decompress(durable.read_bytes())))
    if not candidates:
        proof=json.loads(Path('docs/validation/velvetdelft-20261102.json').read_text())
        data=Path(proof['catalogue_snapshot']['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=proof['catalogue_snapshot']['sha256']:raise ValueError('Reviewed checkpoint checksum mismatch')
        candidates.append(json.loads(gzip.decompress(data)))
    for state in candidates:
        if state.get('shop_id')!='velvetdelft' or state.get('version')!=1:raise ValueError('Wrong source checkpoint')
    state=max(candidates,key=lambda s:(s.get('updated_at',''),s.get('database',{}).get('last_write_at','')))
    save(target,state)
    return state


def persist(path):
    """Only the source checkpoint is written using this step's scoped GitHub token."""
    state=json.loads(Path(path).read_text())
    if state.get('shop_id')!='velvetdelft' or state.get('version')!=1:raise ValueError('Wrong source checkpoint')
    if os.environ.get('GITHUB_REF')!='refs/heads/main':raise ValueError('Checkpoint writes require main')
    repo=os.environ['GITHUB_REPOSITORY']
    endpoint=f'repos/{repo}/contents/{CHECKPOINT}'
    result=subprocess.run(['gh','api',endpoint+'?ref=main'],capture_output=True,text=True)
    previous=None
    if result.returncode==0:
        existing=json.loads(result.stdout);previous=existing['sha']
    elif '404' not in result.stderr:raise RuntimeError('Cannot read durable checkpoint: '+result.stderr[:500])
    # gzip mtime=0 avoids committing changes caused only by compression time.
    data=gzip.compress(json.dumps(state,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)
    blob_sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if previous==blob_sha:
        print('Durable source checkpoint already current');return
    payload={'message':'Checkpoint Velvet Delft EAN collection','branch':'main','content':base64.b64encode(data).decode()}
    if previous:payload['sha']=previous
    with tempfile.TemporaryDirectory() as tmp:
        body=Path(tmp)/'checkpoint.json';body.write_text(json.dumps(payload))
        updated=subprocess.run(['gh','api','--method','PUT',endpoint,'--input',str(body)],capture_output=True,text=True)
    if updated.returncode:raise RuntimeError('Durable checkpoint save failed: '+updated.stderr[:500])
    print('Saved durable Velvet Delft source checkpoint: '+json.loads(updated.stdout)['commit']['sha'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('restore','plan','persist'))
    parser.add_argument('--state',default='output/velvetdelft/state.json')
    parser.add_argument('--automatic',action='store_true')
    parser.add_argument('--extra-initial',action='store_true')
    parser.add_argument('--limit',type=int,default=100)
    args=parser.parse_args()
    if args.command=='restore':restore(args.state);return
    if args.command=='persist':persist(args.state);return
    state=json.loads(Path(args.state).read_text())
    result=plan(state,extra_initial=args.extra_initial) if (args.automatic or args.extra_initial) else {'enabled':True,'phase':'manual','limit':args.limit,'reason':'manual source review'}
    if not 1<=args.limit<=1000:parser.error('Manual limit must be 1..1000')
    result['limit']=min(result['limit'],args.limit)
    done=state.get('database',{}).get('processed_detail_at',{})
    result['database_pending']=any(r.get('detail_observed_at') and done.get(r['source_product_id'])!=r['detail_observed_at'] for r in state['records'].values())
    save(args.state,state)
    save(Path(args.state).parent/'schedule.json',result)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as handle:
            for key in ('enabled','phase','limit','database_pending'):handle.write(f'{key}={str(result[key]).lower()}\n')
    print(json.dumps(result))

if __name__=='__main__':main()
