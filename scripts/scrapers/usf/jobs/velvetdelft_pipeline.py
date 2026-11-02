"""Velvet Delft EAN-gated USF adapter; explicit write mode uses the scoped database secret."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import os
from urllib.parse import urlsplit
from uuid import uuid4
from psycopg.types.json import Jsonb
from scripts.importers.import_velvetdelft import map_velvet_row,CONFIG
from scripts.scrapers.usf.core.models import DiscoveredLink
from scripts.scrapers.usf.core.link_registry import upsert_discovered_links
from scripts.scrapers.usf.core.staging import build_stage_item,stage_latest_raw_snapshots
from scripts.scrapers.usf.core.promotion import PromotionConfig,staged_row_to_record
from scripts.importers.common import ensure_shop,upsert_product,upsert_price,maybe_insert_history,strict_normalize_gtin
from scripts.scrapers.velvetdelft import SHOP_ID,save,safe_url,RELEASE

PROMOTION=PromotionConfig(shop_id=SHOP_ID,shop_name=CONFIG.shop_name,shop_domain=CONFIG.shop_domain,shop_country='NL',currency='EUR')


def load_rows(path):
    data=json.loads(Path(path).read_text())
    if data.get('shop_id')!=SHOP_ID:raise ValueError('Wrong shop capture')
    rows=data['records'];rows=list(rows.values()) if isinstance(rows,dict) else rows
    if len({r['source_product_id'] for r in rows})!=len(rows):raise ValueError('Duplicate release IDs')
    for row in rows:
        safe_url(row['source_url'],True)
        if RELEASE.match(urlsplit(row['source_url']).path)[1]!=str(row['source_product_id']):raise ValueError('Release ID conflict')
    return rows


def raw_row(row):
    return {'id':str(uuid4()),'shop_id':SHOP_ID,'source_url':row['source_url'],'source_product_id':row['source_product_id'],'title_raw':row['artist']+' - '+row['title'],'ean_raw':row.get('ean') or None,'price_raw':row.get('price'),'availability_raw':'unknown' if row['availability']=='supplier_order' else row['availability'],'image_url_raw':None,'scraped_at':max(datetime.fromisoformat(row['listing_observed_at']),datetime.fromisoformat(row.get('detail_observed_at') or row['listing_observed_at'])),'payload':{'listing':row,'format':row['format']}}


def preview(rows):
    identities={}
    for row in rows:
        if row.get('gtin14') and row.get('ean_status')=='verified':
            identities.setdefault(row['gtin14'],set()).add((row.get('artist'),row.get('title'),row.get('format'),row.get('price'),row.get('availability')))
    conflicts={gtin for gtin,offers in identities.items() if len(offers)>1}
    results=[]
    for line,row in enumerate(rows,1):
        record,reason=map_velvet_row(row,line);raw=raw_row(row)
        if row.get('gtin14') in conflicts:record,reason=None,'conflicting_gtin_offers'
        stage=build_stage_item(raw)
        if record:
            staged={'staged_offer_id':'dry-run','source_url':row['source_url'],'source_product_id':row['source_product_id'],'title_raw':raw['title_raw'],'ean_match_key':record.ean,'price':record.price,'availability':record.availability,'currency':'EUR','scraped_at':record.captured_at,'raw_payload':raw['payload']}
            check=staged_row_to_record(row=staged,config=PROMOTION,line_number=line)
            if check.price!=record.price or check.ean!=record.ean:raise ValueError('USF contract disagreement')
        waiting=row.get('ean_status')=='pending' and not row.get('ean') and not row.get('gtin14')
        results.append({'release_id':row['source_product_id'],'stage_reason':stage.stage_reason,'promotion':'valid' if record else 'awaiting_details' if waiting else 'quarantine','reason':reason,'price_source':'listing','price':row.get('price'),'availability':row['availability'],'ean':record.ean if record else None})
    return {'shop_id':SHOP_ID,'database_writes':False,'discovered':len(rows),'stage_valid':sum(not r['stage_reason'] for r in results),'promotion_valid':sum(r['promotion']=='valid' for r in results),'quarantine':sum(r['promotion']=='quarantine' for r in results),'awaiting_details':sum(r['promotion']=='awaiting_details' for r in results),'records':results}


def isolated_only(dsn):
    p=urlsplit(dsn)
    if p.hostname not in ('127.0.0.1','localhost',None) or (p.hostname is None and 'host=/tmp/' not in dsn):
        raise ValueError('Only an explicitly isolated test database is permitted before launch approval')


def ingest(rows,dsn,*,production=False,promote=True):
    """Explicit production opt-in; isolated-only remains the default for tests."""
    import psycopg
    if not production:isolated_only(dsn)
    if os.environ.get('DATABASE_URL')!=dsn:raise ValueError('The explicit database must match DATABASE_URL')
    run=str(uuid4())
    try:return _ingest(rows,dsn,run,production=production,promote=promote)
    except Exception as exc:
        with psycopg.connect(dsn,prepare_threshold=None) as conn:
            conn.execute("update scrape_runs set status='failed',finished_at=now(),error_message=%s where id=%s and shop_id=%s",(str(exc)[:1000],run,SHOP_ID))
        raise


def _ingest(rows,dsn,run,*,production=False,promote=True):
    """Standard USF tables, helpers and transactions, scoped only to Velvet Delft."""
    import psycopg
    if not production:isolated_only(dsn)
    if len(rows)>15000:raise ValueError('Unexpected source size; refusing unbounded writes')
    # Helpers intentionally share the existing DATABASE_URL contract in tests.
    if os.environ.get('DATABASE_URL')!=dsn:raise ValueError('Test DB must match the explicit DATABASE_URL')
    result=preview(rows);good=[];raw_inserted=0;raw_reused=0;products_created=0;prices_inserted=0;prices_changed=0;prices_written=0;history_written=0;quarantined=0;newer_preserved=0
    guarded={r['release_id']:r['reason'] for r in result['records'] if r['reason']}
    waiting={r['release_id'] for r in result['records'] if r['promotion']=='awaiting_details'}
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        conn.execute("insert into scrape_runs(id,shop_id,job_type,status,config) values(%s,%s,'onboarding','running',%s)",(run,SHOP_ID,Jsonb({'isolated_test':not production,'promotion_enabled':promote})))
    # Reuse the existing release link if the storefront changes a slug/URL.
    # Duplicate pre-existing release identities need review, never a broad cleanup.
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        for row in rows:
            existing=conn.execute('select id,source_url from shop_product_links where shop_id=%s and source_product_id=%s for update',(SHOP_ID,row['source_product_id'])).fetchall()
            if len(existing)>1:raise ValueError('Ambiguous existing release links')
            if existing and existing[0][1]!=row['source_url']:
                conn.execute('update shop_product_links set source_url=%s where id=%s and shop_id=%s',(row['source_url'],existing[0][0],SHOP_ID))
    # Preserve prior detail evidence; no delisting is ever performed here.
    links=[DiscoveredLink(SHOP_ID,r['source_url'],r['source_product_id'],{'listing':r}) for r in rows]
    links_result=upsert_discovered_links(links,preserve_payload_keys=('last_successful_ean','last_successful_ean_at'))
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        queue_columns={r[0] for r in conn.execute("select column_name from information_schema.columns where table_schema='public' and table_name='shop_product_links'").fetchall()}
        for i,row in enumerate(rows,1):
            code=strict_normalize_gtin(row.get('ean')) if row.get('ean_status')=='verified' else None
            evidence={'last_successful_ean':row['ean'],'last_successful_ean_at':row['detail_observed_at']} if code and code==row.get('gtin14') else {}
            conn.execute("update shop_product_links set last_detail_scraped_at=%s,payload=coalesce(payload,'{}'::jsonb)||%s where shop_id=%s and source_product_id=%s",(row.get('detail_observed_at'),Jsonb(evidence),SHOP_ID,row['source_product_id']))
            if 'ean_enrichment_status' in queue_columns:
                conn.execute('update shop_product_links set ean_enrichment_status=%s,ean_next_attempt_at=%s where shop_id=%s and source_product_id=%s',('found' if evidence else 'not_found',row.get('detail_next_at') or None,SHOP_ID,row['source_product_id']))
            raw=raw_row(row);signature=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
            # Source release identity and exact snapshot fingerprint: repeat is a no-op.
            exists=conn.execute("select id from raw_shop_scrapes where shop_id=%s and source_product_id=%s and payload->>'capture_fingerprint'=%s limit 1",(SHOP_ID,row['source_product_id'],signature)).fetchone()
            if exists:
                raw_reused+=1
                record,reason=map_velvet_row(row,i)
                if record and row['source_product_id'] not in guarded:good.append((exists[0],record))
                continue
            raw_inserted+=1
            raw['payload']['capture_fingerprint']=signature
            conn.execute("insert into raw_shop_scrapes(id,run_id,shop_id,source_url,source_product_id,title_raw,ean_raw,price_raw,availability_raw,payload,scraped_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(raw['id'],run,SHOP_ID,raw['source_url'],raw['source_product_id'],raw['title_raw'],raw['ean_raw'],raw['price_raw'],raw['availability_raw'],Jsonb(raw['payload']),raw['scraped_at']))
            rec,reason=map_velvet_row(row,i)
            reason=guarded.get(row['source_product_id']) or reason
            if row['source_product_id'] in waiting:continue
            if reason:
                quarantined+=1
                conn.execute("insert into quarantine_offers(shop_id,source_url,issue_type,issue_detail,payload) values(%s,%s,'source_validation',%s,%s)",(SHOP_ID,row['source_url'],reason,Jsonb({'raw_scrape_id':raw['id'],'source':row})))
                # Prevent the shared permissive staging path from admitting rejected sources.
                conn.execute("insert into staged_offers(raw_scrape_id,run_id,shop_id,source_url,source_product_id,stage_status,stage_reason) values(%s,%s,%s,%s,%s,'quarantined',%s)",(raw['id'],run,SHOP_ID,row['source_url'],row['source_product_id'],reason))
            else:good.append((raw['id'],rec))
            if i%50==0:print(json.dumps({'phase':'raw_preparation','processed':i,'target':len(rows)}),flush=True)
    print(json.dumps({'phase':'raw_committed','inserted':raw_inserted,'reused':raw_reused}),flush=True)
    staged=stage_latest_raw_snapshots(shop_id=SHOP_ID,limit=max(1,len(rows)),write=True)
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            shop=ensure_shop(cur,CONFIG)
            if production:
                cur.execute("update shops set shop_type='physical_record_store' where id=%s and shop_type is null",(shop,))
            for promotion_index,(raw_id,record) in enumerate(good,1):
                if not promote:continue
                target=cur.execute("select id from staged_offers where raw_scrape_id=%s and stage_status='staged' for update",(raw_id,)).fetchone()
                if not target:continue
                # Retain newer listing observations and protect canonical metadata.
                old=cur.execute("select p.last_seen_at from prices p join products x on x.id=p.product_id where p.shop_id=%s and x.gtin_normalized=%s for update of p",(shop,record.gtin_normalized)).fetchone()
                if old and old[0] and old[0]>record.captured_at:
                    newer_preserved+=1
                    cur.execute("update staged_offers set stage_status='superseded' where id=%s",(target[0],));continue
                product,created=upsert_product(cur,record);products_created+=int(created)
                inserted,changed=upsert_price(cur,product,shop,record,record.captured_at)
                prices_inserted+=int(inserted);prices_changed+=int(changed);prices_written+=1
                history_written+=int(maybe_insert_history(cur,product,shop,record))
                cur.execute("update staged_offers set stage_status='promoted',stage_reason=null where id=%s",(target[0],))
                if promotion_index%50==0:print(json.dumps({'phase':'promotion_in_transaction','processed':promotion_index,'target':len(good)}),flush=True)
                cur.execute("update quarantine_offers set resolved_at=now() where shop_id=%s and source_url=%s and issue_type='source_validation' and resolved_at is null",(SHOP_ID,record.product_url))
            cur.execute("update scrape_runs set status='completed',finished_at=now(),items_found=%s,items_processed=%s,items_success=%s,items_failed=%s where id=%s",(len(rows),len(rows),result['promotion_valid'],result['quarantine'],run))
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        persisted={table:conn.execute('select count(*) from '+table+' where shop_id=%s',(SHOP_ID,)).fetchone()[0] for table in ('shop_product_links','raw_shop_scrapes','staged_offers','quarantine_offers')}
        persisted['prices']=conn.execute('select count(*) from prices where shop_id=%s',(shop,)).fetchone()[0]
    return {**result,'database_writes':True,'isolated_test':not production,'promotion_enabled':promote,'run_id':run,'shop_id':shop,'usf_shop_id':SHOP_ID,'staged':staged.inserted,'links_inserted':links_result.inserted,'raw_inserted':raw_inserted,'raw_reused':raw_reused,'quarantines_inserted':quarantined,'products_created':products_created,'prices_inserted':prices_inserted,'prices_changed':prices_changed,'prices_written':prices_written,'history_written':history_written,'newer_prices_preserved':newer_preserved,'persisted_counts':persisted}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',required=True)
    p.add_argument('--out',default='output/velvetdelft/database-result.json')
    p.add_argument('--write',action='store_true')
    p.add_argument('--stage-only',action='store_true')
    a=p.parse_args()
    capture=json.loads(Path(a.capture).read_text())
    rows=load_rows(a.capture)
    # Unvisited records stay in the source queue; every completed EAN result is
    # retained in raw/staging/quarantine, including those not yet publishable.
    checked=[r for r in rows if r.get('detail_observed_at')]
    if a.write:
        dsn=os.environ.get('DATABASE_URL')
        if not dsn:raise ValueError('DATABASE_URL is required for write=true')
        report=ingest(checked,dsn,production=True,promote=not a.stage_only and not capture.get('error'))
        capture['database']={'last_write_at':datetime.now(timezone.utc).isoformat(),'last_run_id':report['run_id'],'persisted_counts':report['persisted_counts'],'processed_detail_at':{r['source_product_id']:r['detail_observed_at'] for r in checked}}
        capture['updated_at']=datetime.now(timezone.utc).isoformat()
        save(a.capture,capture)
    else:report=preview(checked)
    save(a.out,report)
    print(json.dumps({k:v for k,v in report.items() if k!='records'},default=str))
if __name__=='__main__':main()
