"""Resumable North End catalogue verification using existing source/import contracts.
One manual chain, bounded jobs, conservative transport, no EAN-less publication.
"""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from urllib.robotparser import RobotFileParser
import requests
from psycopg.types.json import Jsonb
from scripts.workers.northend_album_pilot import canonical_target,parse_source,source_identity
from scripts.scrapers.usf.jobs.refresh_northendhaarlem_listing_prices import category_url,parse_listing_page
from scripts.scrapers.usf.jobs.promote_northendhaarlem import staged_row_to_record
from scripts.importers.common import ImportConfig,ensure_shop,upsert_product,upsert_price,maybe_insert_history
from scripts.scrapers.usf.core.db import db_connection

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/northend-full-catalogue/checkpoint.json'
UA='VinylofyAlbumPilot/1.0'
VERSION=1


def now():return datetime.now(timezone.utc).isoformat()


def seed_records(rows):
    """Freeze identities only; each product uses a freshly re-read listing page."""
    selected={}
    for row in rows:
        if row.get('shop_domain')!='northendhaarlem.nl' or row.get('currency')!='EUR':raise ValueError('Wrong source shop/currency')
        ident=source_identity(row['source_url']);raw=row['raw']
        if raw.get('source_product_id')!=ident:raise ValueError('Source ID mismatch')
        seed={'category_id':str(raw['category_id']),'slug':raw['category_slug'],'name':raw['category_name']}
        page=int(raw['page'])
        if not re.fullmatch(r'\d+',seed['category_id']) or not re.fullmatch(r'[a-z0-9-]+',seed['slug']) or not 1<=page<=1000:raise ValueError('Invalid listing provenance')
        item={'source_product_id':ident,'source_url':row['source_url'],'title_raw':raw['title_raw'],
              'seed':seed,'page':page,'initial_availability':row.get('availability')}
        if ident in selected and selected[ident]['title_raw']!=item['title_raw']:raise ValueError('Conflicting source ID')
        selected.setdefault(ident,item)
    if not 1<=len(selected)<=20000:raise ValueError('Empty or oversized source catalogue')
    return sorted(selected.values(),key=lambda r:(r['source_product_id']!='117366946',r['initial_availability']!='in_stock',int(r['source_product_id'])))


def initialize(rows,source_run,chain_id):
    records=seed_records(rows)
    return {'version':VERSION,'source_run':source_run,'chain_id':chain_id,'created_at':now(),
            'seed_sha256':hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest(),
            'records':records,'results':{},'cursor':0,'status':'ready','production_write':False}


def validate_checkpoint(state):
    if state.get('version')!=VERSION:raise ValueError('Unsupported checkpoint version')
    records=state['records'];cursor=state['cursor']
    if not 1<=len(records)<=20000 or not 0<=cursor<=len(records):raise ValueError('Invalid checkpoint bounds')
    if hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()!=state['seed_sha256']:raise ValueError('Checkpoint identities changed')
    if len({r['source_product_id'] for r in records})!=len(records):raise ValueError('Duplicate checkpoint identities')
    if set(state['results'])!={r['source_product_id'] for r in records[:cursor]}:raise ValueError('Checkpoint progress is not contiguous')
    for item in records:
        if source_identity(item['source_url'])!=item['source_product_id']:raise ValueError('Invalid checkpoint source')


def save(state):
    state['updated_at']=now()
    state['summary']={'total':len(state['records']),'processed':state['cursor'],'remaining':len(state['records'])-state['cursor'],
      'statuses':dict(Counter(r['status'] for r in state['results'].values())),
      'routes':dict(Counter(r.get('route','none') for r in state['results'].values())),
      'database_results':dict(Counter(r.get('database',{}).get('status','none') for r in state['results'].values()))}
    OUT.parent.mkdir(parents=True,exist_ok=True);temp=OUT.with_suffix('.tmp')
    temp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(OUT)


class Transport:
    def __init__(self):
        self.session=requests.Session();self.session.headers.update({'User-Agent':UA,'Accept-Language':'nl-NL,nl;q=0.9'})
        self.last=None;self.delay=30.;self.robot=None
    def get(self,url):
        if self.robot and not self.robot.can_fetch(UA,url):raise ValueError('robots_disallow')
        if self.last is not None:time.sleep(max(0,self.delay-(time.monotonic()-self.last)))
        self.last=time.monotonic()
        with self.session.get(url,timeout=30,stream=True,allow_redirects=False) as response:
            if response.status_code!=200:raise RuntimeError('HTTP_'+str(response.status_code))
            raw=response.raw.read(2000001,decode_content=True)
            if len(raw)>2000000:raise RuntimeError('Response exceeds size limit')
            body=raw.decode(response.encoding or 'utf-8',errors='replace')
            if re.search(r'cf-chl-|challenge-platform|<title>Just a moment',body,re.I):raise RuntimeError('ACCESS_CHALLENGE')
            return body
    def start(self):
        robot=RobotFileParser();robot.parse(self.get('https://www.northendhaarlem.nl/robots.txt').splitlines());self.robot=robot
        self.delay=max(self.delay,robot.crawl_delay(UA) or robot.crawl_delay('*') or 0)
    def close(self):self.session.close()


def verify_item(item,transport,listing_cache):
    url=category_url(item['seed'],item['page'])
    if url not in listing_cache:
        body=transport.get(url);stamp=now()
        listing_cache[url]=parse_listing_page(body,discovery_url=url,seed=item['seed'],page=item['page'],seen_at=stamp)
    matches=[r for r in listing_cache[url] if r.link.source_product_id==item['source_product_id']]
    if len(matches)!=1:raise ValueError('Source article absent or ambiguous on current listing page')
    row=matches[0].link;payload=row.payload
    current={'source_product_id':row.source_product_id,'source_url':row.source_url,'title_raw':payload['title_raw'],
      'listing_price':payload['price'],'currency':'EUR','listing_availability':payload['availability'],
      'listing_observed_at':payload['listing_seen_at']}
    body=transport.get(current['source_url']);target=canonical_target(body,current)
    target_body=transport.get(target) if target else None
    result=parse_source(body,current,now(),canonical_body=target_body,require_in_stock=False)
    result['listing_source_url']=url
    return result


def persist_result(conn,result,chain_id):
    """Reuse the production EAN importer; EAN-less records only enter raw storage.
    A row transaction and deterministic raw ID make replay after a crash safe.
    """
    if result.get('status')!='validated':raise ValueError('Unvalidated result cannot be written')
    source_identity(result['source_url'])
    price=Decimal(result['price'])
    if not price.is_finite() or price<=0 or result.get('currency')!='EUR' or result.get('format_status')!='vinyl' or result.get('condition_status')!='new':
        raise ValueError('Invalid price/currency/format/condition for database write')
    stamp=datetime.fromisoformat(result['listing_observed_at'])
    age=(datetime.now(timezone.utc)-stamp).total_seconds()
    if not 0<=age<48*3600:raise ValueError('Listing price expired before write')
    raw_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'northend-full:'+chain_id+':'+result['source_product_id']))
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("set local lock_timeout='5s';set local statement_timeout='30s'")
            # Serialize retries of the same source record; all associated writes
            # commit together with this raw evidence marker.
            cur.execute('select pg_advisory_xact_lock(hashtextextended(%s,0))',(raw_id,))
            cur.execute('select id from public.raw_shop_scrapes where id=%s',(raw_id,))
            if cur.fetchone():return {'status':'already_written','raw_id':raw_id}
            raw={**result,'full_catalogue_chain_id':chain_id,'price_source':'listing'}
            cur.execute("""insert into public.raw_shop_scrapes(id,run_id,shop_id,source_url,source_product_id,title_raw,
              ean_raw,price_raw,availability_raw,image_url_raw,payload)
              values(%s,null,'northendhaarlem',%s,%s,%s,%s,%s,%s,null,%s)""",
              (raw_id,result['source_url'],result['source_product_id'],result['source_title'],result.get('gtin14'),
               result['price'],result['availability'],Jsonb(raw)))
            if result['route']!='EAN':return {'status':'raw_album_review_only','raw_id':raw_id}
            from scripts.scrapers.usf.jobs.detail_northendhaarlem import normalize_ean
            if not normalize_ean(result.get('gtin14')):raise ValueError('EAN route lacks a valid identifier')
            row={'staged_offer_id':raw_id,'ean_match_key':result['gtin14'],'title_raw':result['source_title'],
              'price':Decimal(result['price']),'availability':result['availability'],'currency':'EUR',
              'source_url':result.get('canonical_url') or result['source_url'],'source_product_id':result.get('canonical_source_product_id') or result['source_product_id'],
              'scraped_at':stamp}
            record=staged_row_to_record(row,1)
            shop_id=ensure_shop(cur,ImportConfig(shop_name='North End Haarlem',shop_domain='northendhaarlem.nl',shop_country='NL',currency='EUR'))
            product_id,inserted=upsert_product(cur,record)
            # Prices remain listing-first, including their actual observation time.
            cur.execute('select last_seen_at from public.prices where product_id=%s and shop_id=%s for update',(product_id,shop_id))
            existing=cur.fetchone()
            if existing and existing[0] and existing[0]>stamp:return {'status':'ean_kept_newer_listing_price','raw_id':raw_id,'product_id':str(product_id)}
            price_inserted,changed=upsert_price(cur,product_id,shop_id,record,stamp)
            history=maybe_insert_history(cur,product_id,shop_id,record)
            return {'status':'ean_imported','raw_id':raw_id,'product_id':str(product_id),'new_product':inserted,
                    'new_price':price_inserted,'price_changed':changed,'history_inserted':history}


def run_batch(state,transport,*,batch_size=50,writer=None,budget_seconds=5400):
    validate_checkpoint(state)
    if not 1<=batch_size<=100:raise ValueError('Batch size must be 1..100')
    start=time.monotonic();cache={};state['status']='running';save(state)
    try:
        transport.start()
        for item in state['records'][state['cursor']:state['cursor']+batch_size]:
            if time.monotonic()-start>budget_seconds:break
            try:
                result=verify_item(item,transport,cache)
            except requests.RequestException:
                state['status']='network_paused';state['stop_reason']='transport_failure';save(state);return state
            except Exception as error:
                message=str(error)
                if message in ('HTTP_401','HTTP_403','HTTP_429','ACCESS_CHALLENGE') or re.fullmatch(r'HTTP_5\d\d',message):
                    state['status']='access_paused';state['stop_reason']=message;save(state);return state
                result={'source_product_id':item['source_product_id'],'source_url':item['source_url'],'status':'blocked','reason':message}
            if result['status']=='validated' and writer:
                # Database faults are infrastructure failures. Stop at this same
                # cursor; do not consume every remaining product as a failure.
                result['production_write']=True
                result['database']=writer(result)
            state['results'][item['source_product_id']]=result;state['cursor']+=1;save(state)
            print(json.dumps({'processed':state['cursor'],'total':len(state['records']),'source_product_id':item['source_product_id'],
              'status':result['status'],'route':result.get('route'),'database':result.get('database',{}).get('status')}),flush=True)
        state['status']='completed' if state['cursor']==len(state['records']) else 'continue'
    except Exception as error:
        message=str(error)
        access=message in ('HTTP_401','HTTP_403','HTTP_429','ACCESS_CHALLENGE') or bool(re.fullmatch(r'HTTP_5\d\d',message))
        state['status']='access_paused' if access else 'infrastructure_paused'
        state['stop_reason']=message if access else type(error).__name__;save(state);raise
    finally:transport.close()
    save(state);return state


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seed');parser.add_argument('--source-run',required=True)
    parser.add_argument('--resume');parser.add_argument('--batch-size',type=int,default=50);parser.add_argument('--write',action='store_true');args=parser.parse_args()
    if args.resume:
        state=json.loads(Path(args.resume).read_text(encoding='utf-8-sig'));validate_checkpoint(state)
        if state['production_write']!=args.write or state['source_run']!=args.source_run:raise ValueError('Resume cannot change source or write mode')
    else:state=initialize(json.loads(Path(args.seed).read_text(encoding='utf-8-sig')),args.source_run,os.environ['GITHUB_RUN_ID'])
    state['production_write']=args.write
    transport=Transport()
    if args.write:
        with db_connection() as conn:run_batch(state,transport,batch_size=args.batch_size,writer=lambda r:persist_result(conn,r,state['chain_id']))
    else:run_batch(state,transport,batch_size=args.batch_size)
    print(json.dumps({'status':state['status'],'summary':state['summary']}),flush=True)
    if state['status'] not in ('continue','completed'):raise SystemExit(1)

if __name__=='__main__':main()
