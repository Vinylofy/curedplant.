"""Read-only production contract check for the Velvet Delft USF pipeline."""
import json
import argparse
import os
from pathlib import Path
import psycopg
from scripts.scrapers.velvetdelft import save

TABLES=('scrape_runs','shop_product_links','raw_shop_scrapes','staged_offers','quarantine_offers','shops','products','prices','price_history')


def audit():
    dsn=os.environ.get('DATABASE_URL')
    if not dsn:raise ValueError('DATABASE_URL is required')
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        conn.execute('set transaction read only')
        privileges=conn.execute("select t,p,has_table_privilege(current_user,'public.'||t,p) from unnest(%s::text[]) as t cross join unnest(array['SELECT','INSERT','UPDATE']) as p",(list(TABLES),)).fetchall()
        columns=conn.execute("select table_name,column_name,data_type,is_nullable,column_default from information_schema.columns where table_schema='public' and table_name=any(%s) order by table_name,ordinal_position",(list(TABLES),)).fetchall()
        checks=conn.execute("select c.relname,con.conname,pg_get_constraintdef(con.oid) from pg_constraint con join pg_class c on c.oid=con.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relname=any(%s) and con.contype in ('c','f')",(list(TABLES),)).fetchall()
        shops=conn.execute("select id,name,domain,country from shops where lower(domain) in ('velvetdelft.nl','www.velvetdelft.nl') or lower(name) in ('velvet delft','velvet music delft')").fetchall()
        samples=conn.execute("select x.id,x.gtin_normalized,x.artist,x.title,p.price,p.availability,p.last_seen_at,p.product_url from prices p join products x on x.id=p.product_id join shops s on s.id=p.shop_id where lower(s.domain) in ('velvetdelft.nl','www.velvetdelft.nl') order by (p.availability='in_stock') desc,p.last_seen_at desc limit 5").fetchall()
        snapshot=None
        if conn.execute("select to_regclass('public.shop_catalog_daily_dashboard_v2')").fetchone()[0]:
            snapshot=conn.execute("select to_jsonb(v) from public.shop_catalog_daily_dashboard_v2 v join shops s on s.id=v.shop_id where s.domain='velvetdelft.nl' order by v.snapshot_day desc limit 1").fetchone()
            snapshot=snapshot[0] if snapshot else None
        price_count=conn.execute("select count(*) from prices p join shops s on s.id=p.shop_id where lower(s.domain) in ('velvetdelft.nl','www.velvetdelft.nl')").fetchone()[0]
        counts={t:conn.execute('select count(*) from '+t+' where shop_id=%s',('velvetdelft',)).fetchone()[0] for t in TABLES[:5]}
    return {'database_writes':False,'write_capabilities':privileges,'columns':columns,'constraints':checks,'registered_shops':[list(map(str,r)) for r in shops],'usf_counts':counts,'price_count':price_count,'monitor_snapshot':snapshot,'offer_samples':[[str(v) for v in row] for row in samples]}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--require-write',action='store_true');parser.add_argument('--refresh-monitor',action='store_true');args=parser.parse_args()
    if args.refresh_monitor:
        with psycopg.connect(os.environ['DATABASE_URL'],prepare_threshold=None) as conn:
            conn.execute("select * from public.refresh_shop_catalog_daily((now() at time zone 'Europe/Amsterdam')::date,48)")
    result=audit();save('output/velvetdelft/database-audit.json',result)
    if args.require_write and not all(row[2] for row in result['write_capabilities']):raise ValueError('Required USF database write privileges are missing; source collection stays off')
    print(json.dumps(result,default=str))
