"""Resumable, credential-free A Tube catalogue/detail collection. No DB access."""
import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from scripts.scrapers import atubehighfidelity as shop


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)


def signature(row):
    return hashlib.sha256(json.dumps([row.get(k) for k in ('source_product_id','title_raw','price','currency','format_status','condition_status')]).encode()).hexdigest()


def collect(path, batch_size=25, refresh=False, transport=None, listing_only=False):
    state = json.loads(path.read_text()) if path.exists() else {'version':1,'shop':shop.DOMAIN,'records':[]}
    if state.get('version') != 1 or state.get('shop') != shop.DOMAIN:
        raise ValueError('Unrecognized source checkpoint')
    if not 1 <= batch_size <= 100:
        raise ValueError('Detail batch is 1..100')
    client = transport or shop.AtubeTransport(shop.DOMAIN)
    state['request_history']=state.get('request_history',[])+state.get('requests',[])
    batch=[];state['batch_urls']=[];state['error']=None;state['requests']=client.requests
    parser = hashlib.sha256(Path(shop.__file__).read_bytes()).hexdigest()
    try:
        client.start(shop.CATALOGUE)
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(state['created_at'])).total_seconds() if state.get('created_at') else float('inf')
        if refresh or not state.get('pagination',{}).get('complete') or age > 24*3600:
            old = {r['source_url']:r for r in state['records']}
            observed=shop.stamp();rows=[]
            rows,pagination=shop.catalogue(client,1000,observed,rows)
            if not pagination['complete']:
                raise ValueError('Catalogue end not proven')
            for row in rows:
                listing_reasons=list(row['review_reasons'])
                prior=old.get(row['source_url'])
                same=prior and signature(row)==prior.get('input_signature') and state.get('parser_sha256')==parser
                if same:
                    row={**prior,'listing_observed_at':observed}
                    if row.get('detail_observed_at') and (datetime.now(timezone.utc)-datetime.fromisoformat(row['detail_observed_at'])).total_seconds()>48*3600:
                        row.update(detail_status='not_sampled',status='pending',attempts=0)
                row['input_signature']=signature(row)
                row['listing_review_reasons']=listing_reasons
                if listing_reasons:
                    row.update(status='excluded',cycle_reason=';'.join(listing_reasons))
                row.setdefault('status','pending')
                row.setdefault('attempts',0)
                old[row['source_url']]=row
            state.update(records=[old[r['source_url']] for r in rows],pagination=pagination,created_at=observed,parser_sha256=parser)
            save(path,state)
        elif state.get('parser_sha256') != parser:
            # New code revalidates previous successes; frozen items require manual review.
            for row in state['records']:
                if row.get('status')=='validated':row.update(detail_status='not_sampled',status='pending',attempts=0)
            state['parser_sha256']=parser
        pending=[r for r in state['records'] if r.get('status') not in ('validated','excluded','frozen')]
        pending.sort(key=lambda r:r.get('attempts',0))
        for row in pending[:0 if listing_only else batch_size]:
            row['attempts']=row.get('attempts',0)+1
            state['batch_urls'].append(row['source_url'])
            try:
                row.update(shop.parse_detail(client.get(row['source_url']),{**row,'review_reasons':row.get('listing_review_reasons',[])},shop.stamp()))
                if row['status']!='validated':
                    row.update(status='frozen' if row['attempts']>=3 else 'retry',cycle_reason=';'.join(row['review_reasons']))
            except ValueError as error:
                row.update(status='frozen' if row['attempts']>=3 else 'retry',detail_status='review',cycle_reason=str(error))
            except Exception as error:
                row.update(status='frozen' if row['attempts']>=3 else 'retry',detail_status='technical_error',cycle_reason=str(error))
                state['error']=type(error).__name__+': '+str(error)
                save(path,state)
                break  # Access/network failures stop this shop; never evade or hammer it.
            finally:
                batch.append(row['source_url']);save(path,state)
    except Exception as error:
        state['error']=type(error).__name__+': '+str(error)
    finally:
        if transport is None:client.close()
    counts=Counter(r.get('status','pending') for r in state['records'])
    waiting=sum(counts.get(s,0) for s in ('pending','retry'))
    state.update(status='failed' if state['error'] else 'success',complete=not state['error'] and bool(state.get('pagination',{}).get('complete')) and waiting==0,
                 counts=dict(counts),waiting=waiting,updated_at=shop.stamp(),batch_urls=batch,database_writes=0)
    save(path,state)
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,default=Path('output/atubehighfidelity/state.json'))
    parser.add_argument('--output',type=Path,default=Path('output/atubehighfidelity/result.json'))
    parser.add_argument('--batch-size',type=int,default=25)
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--listing-only',action='store_true')
    parser.add_argument('--until-complete',action='store_true')
    parser.add_argument('--max-seconds',type=int,default=1200)
    args=parser.parse_args()
    # Listing-only uses the same catalogue cache but preserves all detail checkpoints.
    started=time.monotonic()
    while True:
        result=collect(args.state,args.batch_size,args.refresh,listing_only=args.listing_only)
        args.refresh=False
        save(args.output,result)
        print(json.dumps({k:result[k] for k in ('complete','counts','waiting','error','database_writes')}),flush=True)
        if not args.until_complete or args.listing_only or result['complete'] or result['error'] or time.monotonic()-started>args.max_seconds:
            break
    save(args.output,result)
    with args.output.with_name('products.csv').open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=shop.FIELDS,extrasaction='ignore');writer.writeheader();writer.writerows(result['records'])
    return 1 if result['error'] else 0


if __name__=='__main__':raise SystemExit(main())
