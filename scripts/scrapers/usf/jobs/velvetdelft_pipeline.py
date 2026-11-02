"""Velvet Delft USF adapter. Public workflows preview only; writes require isolated DB."""
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
from scripts.importers.common import ensure_shop,upsert_product,upsert_price,maybe_insert_history
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
    return {'id':str(uuid4()),'shop_id':SHOP_ID,'source_url':row['source_url'],'source_product_id':row['source_product_id'],'title_raw':row['artist']+' - '+row['title'],'ean_raw':row.get('ean') or None,'price_raw':row.get('price'),'availability_raw':'unknown' if row['availability']=='supplier_order' else row['availability'],'image_url_raw':None,'scraped_at':datetime.fromisoformat(row['listing_observed_at']),'payload':{'listing':row,'format':row['format']}}


def preview(rows):
    results=[]
    for line,row in enumerate(rows,1):
        record,reason=map_velvet_row(row,line);raw=raw_row(row)
        stage=build_stage_item(raw)
        if record:
            staged={'staged_offer_id':'dry-run','source_url':row['source_url'],'source_product_id':row['source_product_id'],'title_raw':raw['title_raw'],'ean_match_key':record.ean,'price':record.price,'availability':record.availability,'currency':'EUR','scraped_at':record.captured_at,'raw_payload':raw['payload']}
            check=staged_row_to_record(row=staged,config=PROMOTION,line_number=line)
            if check.price!=record.price or check.ean!=record.ean:raise ValueError('USF contract disagreement')
        results.append({'release_id':row['source_product_id'],'stage_reason':stage.stage_reason,'promotion':'valid' if record else 'quarantine','reason':reason,'price_source':'listing','price':row.get('price'),'availability':row['availability'],'ean':record.ean if record else None})
    return {'shop_id':SHOP_ID,'database_writes':False,'discovered':len(rows),'stage_valid':sum(not r['stage_reason'] for r in results),'promotion_valid':sum(r['promotion']=='valid' for r in results),'quarantine':sum(r['promotion']=='quarantine' for r in results),'records':results}


def isolated_only(dsn):
    p=urlsplit(dsn)
    if p.hostname not in ('127.0.0.1','localhost',None) or (p.hostname is None and 'host=/tmp/' not in dsn):
        raise ValueError('Only an explicitly isolated test database is permitted before launch approval')


def ingest(rows,dsn):
    """Standard USF tables, helpers and transactions. Test-only mutation entrypoint."""
    import psycopg
    isolated_only(dsn)
    # Helpers intentionally share the existing DATABASE_URL contract in tests.
    if os.environ.get('DATABASE_URL')!=dsn:raise ValueError('Test DB must match the explicit DATABASE_URL')
    result=preview(rows);run=str(uuid4());good=[]
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        conn.execute("insert into scrape_runs(id,shop_id,job_type,status,config) values(%s,%s,'onboarding','running',%s)",(run,SHOP_ID,Jsonb({'isolated_test':True})))
    # Preserve prior detail evidence/URL; no delisting is ever performed here.
    links=[DiscoveredLink(SHOP_ID,r['source_url'],r['source_product_id'],{'listing':r}) for r in rows]
    upsert_discovered_links(links,preserve_payload_keys=('last_successful_ean','last_successful_ean_at'))
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        for i,row in enumerate(rows,1):
            raw=raw_row(row);signature=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
            # Source release identity and exact snapshot fingerprint: repeat is a no-op.
            exists=conn.execute("select id from raw_shop_scrapes where shop_id=%s and source_product_id=%s and payload->>'capture_fingerprint'=%s limit 1",(SHOP_ID,row['source_product_id'],signature)).fetchone()
            if exists:continue
            raw['payload']['capture_fingerprint']=signature
            conn.execute("insert into raw_shop_scrapes(id,run_id,shop_id,source_url,source_product_id,title_raw,ean_raw,price_raw,availability_raw,payload,scraped_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(raw['id'],run,SHOP_ID,raw['source_url'],raw['source_product_id'],raw['title_raw'],raw['ean_raw'],raw['price_raw'],raw['availability_raw'],Jsonb(raw['payload']),raw['scraped_at']))
            rec,reason=map_velvet_row(row,i)
            if reason:
                conn.execute("insert into quarantine_offers(shop_id,source_url,issue_type,issue_detail,payload) values(%s,%s,'source_validation',%s,%s)",(SHOP_ID,row['source_url'],reason,Jsonb({'raw_scrape_id':raw['id'],'source':row})))
                # Prevent the shared permissive staging path from admitting rejected sources.
                conn.execute("insert into staged_offers(raw_scrape_id,run_id,shop_id,source_url,source_product_id,stage_status,stage_reason) values(%s,%s,%s,%s,%s,'quarantined',%s)",(raw['id'],run,SHOP_ID,row['source_url'],row['source_product_id'],reason))
            else:good.append((raw['id'],rec))
    staged=stage_latest_raw_snapshots(shop_id=SHOP_ID,limit=max(1,len(rows)),write=True)
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            shop=ensure_shop(cur,CONFIG)
            for raw_id,record in good:
                target=cur.execute("select id from staged_offers where raw_scrape_id=%s and stage_status='staged' for update",(raw_id,)).fetchone()
                if not target:continue
                # Retain newer listing observations and protect canonical metadata.
                old=cur.execute("select p.last_seen_at from prices p join products x on x.id=p.product_id where p.shop_id=%s and x.gtin_normalized=%s for update of p",(shop,record.gtin_normalized)).fetchone()
                if old and old[0] and old[0]>record.captured_at:
                    cur.execute("update staged_offers set stage_status='superseded' where id=%s",(target[0],));continue
                product,_=upsert_product(cur,record)
                upsert_price(cur,product,shop,record,record.captured_at)
                maybe_insert_history(cur,product,shop,record)
                cur.execute("update staged_offers set stage_status='promoted',stage_reason=null where id=%s",(target[0],))
            cur.execute("update scrape_runs set status='completed',finished_at=now(),items_found=%s,items_processed=%s,items_success=%s,items_failed=%s where id=%s",(len(rows),len(rows),result['promotion_valid'],result['quarantine'],run))
    return {**result,'database_writes':True,'isolated_test':True,'staged':staged.inserted}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',required=True);p.add_argument('--out',default='output/velvetdelft/pipeline-preview.json');a=p.parse_args()
    report=preview(load_rows(a.capture));save(a.out,report);print(json.dumps({k:v for k,v in report.items() if k!='records'}))
if __name__=='__main__':main()
