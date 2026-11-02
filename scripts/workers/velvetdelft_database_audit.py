"""Read-only production contract check for the Velvet Delft USF pipeline."""
import json
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
        columns=conn.execute("select table_name,column_name,data_type,is_nullable,column_default from information_schema.columns where table_schema='public' and table_name=any(%s) order by table_name,ordinal_position",(list(TABLES),)).fetchall()
        checks=conn.execute("select c.relname,con.conname,pg_get_constraintdef(con.oid) from pg_constraint con join pg_class c on c.oid=con.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relname=any(%s) and con.contype in ('c','f')",(list(TABLES),)).fetchall()
        shops=conn.execute("select id,name,domain,country from shops where lower(domain) in ('velvetdelft.nl','www.velvetdelft.nl') or lower(name) in ('velvet delft','velvet music delft')").fetchall()
        counts={t:conn.execute('select count(*) from '+t+' where shop_id=%s',('velvetdelft',)).fetchone()[0] for t in TABLES[:5]}
    return {'database_writes':False,'columns':columns,'constraints':checks,'registered_shops':[list(map(str,r)) for r in shops],'usf_counts':counts}

if __name__=='__main__':
    result=audit();save('output/velvetdelft/database-audit.json',result);print(json.dumps(result,default=str))
