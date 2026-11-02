"""Real USF integration checks. ONLY a disposable isolated database is accepted."""
import copy
from datetime import datetime,timedelta,timezone
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import psycopg
from tests.test_velvetdelft import good
from scripts.scrapers.usf.jobs.velvetdelft_pipeline import ingest,isolated_only,preview,sync_existing_prices

DSN=os.environ.get('VELVET_TEST_DATABASE_URL')
BUSINESS_SCHEMA='''
create table shops(id uuid primary key default gen_random_uuid(),name text,domain text unique,country text,shop_type text,is_active boolean default true,updated_at timestamptz default now());
create table products(id uuid primary key default gen_random_uuid(),ean text unique,gtin_normalized text unique,artist text,title text,format_label text,cover_url text,canonical_key text,artist_normalized text,title_normalized text,search_text text,metadata_source text,metadata_status text,metadata_confidence numeric,metadata_needs_review boolean,created_at timestamptz default now(),updated_at timestamptz default now());
create table prices(product_id uuid references products(id),shop_id uuid references shops(id),price numeric,currency text,product_url text,availability text,first_seen_at timestamptz,last_seen_at timestamptz,is_active boolean,ean_raw text,gtin_normalized text,created_at timestamptz,updated_at timestamptz,primary key(product_id,shop_id));
create table price_history(product_id uuid,shop_id uuid,price numeric,currency text,availability text,captured_at timestamptz,created_at timestamptz);
'''

@unittest.skipUnless(DSN,'Set VELVET_TEST_DATABASE_URL to a disposable isolated PostgreSQL')
class PipelinePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        isolated_only(DSN)
        with psycopg.connect(DSN) as conn:
            conn.execute((Path(__file__).parent/'fixtures/velvetdelft/usf-schema.sql').read_text())
            conn.execute(BUSINESS_SCHEMA)
    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DSN) as conn:
            conn.execute('drop table price_history,prices,products,shops,quarantine_offers,staged_offers,raw_shop_scrapes,shop_product_links,scrape_runs cascade')
    def setUp(self):
        self.env=patch.dict(os.environ,{'DATABASE_URL':DSN});self.env.start();self.addCleanup(self.env.stop)
        with psycopg.connect(DSN) as conn:
            conn.execute('truncate price_history,prices,products,shops,quarantine_offers,staged_offers,raw_shop_scrapes,shop_product_links,scrape_runs cascade')
    def test_real_100_release_sample_through_staging_promotion_and_quarantine(self):
        import json
        data=json.loads((Path(__file__).parent/'fixtures/velvetdelft/sample100.json').read_text())
        rows=copy.deepcopy(data['records'])
        # These are fixed source fixtures: keep all real prices/barcodes, renew
        # only the test clock so the freshness contract remains testable later.
        for row in rows:
            row['listing_observed_at']=datetime.now(timezone.utc).isoformat()
            row['detail_observed_at']=row['listing_observed_at']
        expected=preview(rows)
        self.assertEqual((expected['discovered'],expected['promotion_valid'],expected['quarantine']),(100,92,8))
        ingest(rows,DSN);ingest(rows,DSN)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select count(*) from raw_shop_scrapes').fetchone()[0],100)
            self.assertEqual(conn.execute('select count(*) from products').fetchone()[0],92)
            self.assertEqual(conn.execute('select count(*) from prices').fetchone()[0],92)
            self.assertEqual(conn.execute('select count(*) from quarantine_offers').fetchone()[0],8)
    def test_complete_usf_chain_and_repeat_idempotency(self):
        r=good();a=ingest([r],DSN);self.assertEqual(a['staged'],1)
        b=ingest([r],DSN);self.assertEqual(b['staged'],0)
        with psycopg.connect(DSN) as conn:
            for table in ['shop_product_links','raw_shop_scrapes','staged_offers','products','prices','price_history']:
                self.assertEqual(conn.execute('select count(*) from '+table).fetchone()[0],1,table)
            self.assertEqual(conn.execute('select stage_status from staged_offers').fetchone()[0],'promoted')
            self.assertEqual(conn.execute('select last_seen_at from prices').fetchone()[0].isoformat(),r['listing_observed_at'])
    def test_invalid_barcode_never_reaches_product_and_quarantine_is_idempotent(self):
        r={**good(),'ean':'8720589667908'};ingest([r],DSN);ingest([r],DSN)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select count(*) from products').fetchone()[0],0)
            self.assertEqual(conn.execute('select count(*) from quarantine_offers').fetchone()[0],1)
            self.assertEqual(conn.execute('select stage_status from staged_offers').fetchone()[0],'quarantined')
    def test_unknown_and_supplier_never_become_stock(self):
        r={**good(),'availability':'supplier_order'};ingest([r],DSN)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select availability from prices').fetchone()[0],'unknown')
            payload=conn.execute('select payload from raw_shop_scrapes').fetchone()[0]
            self.assertEqual(payload['listing']['availability'],'supplier_order')
    def test_older_listing_cannot_overwrite_newer_price_or_canonical_metadata(self):
        r=good();ingest([r],DSN)
        with psycopg.connect(DSN) as conn:
            conn.execute("update products set artist='Canonical artist',title='Canonical album',metadata_source='musicbrainz',metadata_status='verified'")
            conn.execute("update prices set price=22,last_seen_at=now()+interval '1 minute'")
        old={**r,'price':'1.00','listing_observed_at':(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()};ingest([old],DSN)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(float(conn.execute('select price from prices').fetchone()[0]),22.)
            self.assertEqual(conn.execute('select artist,title from products').fetchone(),('Canonical artist','Canonical album'))
            self.assertEqual(conn.execute('select count(*) from price_history').fetchone()[0],1)
    def test_changed_listing_url_reuses_release_and_preserves_canonical_metadata(self):
        r=good();ingest([r],DSN)
        with psycopg.connect(DSN) as conn:
            old=conn.execute('select id from shop_product_links').fetchone()[0]
            conn.execute("update products set artist='Canonical artist',title='Canonical album',metadata_source='musicbrainz',metadata_status='verified'")
        changed={**r,'source_url':r['source_url'].replace('Fatal-Flowers','Fatal-Flowers-New-Slug'),'price':'20.99'}
        ingest([changed],DSN)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select id from shop_product_links').fetchall(),[(old,)])
            self.assertEqual(conn.execute('select artist,title from products').fetchone(),('Canonical artist','Canonical album'))
            self.assertEqual(float(conn.execute('select price from prices').fetchone()[0]),20.99)
    def test_interrupted_promotion_resumes_existing_staged_snapshot(self):
        r=good()
        with patch('scripts.scrapers.usf.jobs.velvetdelft_pipeline.upsert_product',side_effect=RuntimeError('simulated DB failure')):
            with self.assertRaises(RuntimeError):ingest([r],DSN)
        result=ingest([r],DSN)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select count(*) from raw_shop_scrapes').fetchone()[0],1)
            self.assertEqual(conn.execute('select count(*) from prices').fetchone()[0],1)
            self.assertEqual(conn.execute('select stage_status from staged_offers').fetchone()[0],'promoted')
            self.assertEqual(conn.execute("select count(*) from scrape_runs where status='failed'").fetchone()[0],1)
            self.assertEqual(conn.execute("select count(*) from scrape_runs where status='running'").fetchone()[0],0)
    def test_authorized_production_path_and_actual_write_counts(self):
        result=ingest([good()],DSN,production=True)
        self.assertFalse(result['isolated_test'])
        self.assertEqual((result['raw_inserted'],result['prices_written'],result['persisted_counts']['prices']),(1,1,1))
        repeat=ingest([good()],DSN,production=True)
        # A new fixture observation is a new source snapshot; no duplicate product.
        self.assertEqual(repeat['persisted_counts']['prices'],1)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select shop_type from shops').fetchone()[0],'physical_record_store')
    def test_stage_only_retains_ean_without_publishing_prices(self):
        result=ingest([good()],DSN,promote=False)
        self.assertEqual((result['raw_inserted'],result['staged'],result['prices_written']),(1,1,0))
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select count(*) from products').fetchone()[0],0)
            self.assertEqual(conn.execute('select stage_status from staged_offers').fetchone()[0],'staged')
    def test_price_refresh_uses_bulk_existing_offers_and_does_not_restage_catalogue(self):
        row=good();row['listing_observed_at']=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
        ingest([row],DSN)
        refreshed={**row,'price':'20.99','availability':'supplier_order','listing_observed_at':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()}
        result=sync_existing_prices([refreshed],DSN)
        self.assertEqual((result['new_offers'],result['prices_verified'],result['raw_inserted']),(0,1,0))
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select count(*) from raw_shop_scrapes').fetchone()[0],1)
            self.assertEqual(conn.execute('select availability from prices').fetchone()[0],'unknown')
            self.assertEqual(float(conn.execute('select price from prices').fetchone()[0]),20.99)
    def test_price_becoming_available_promotes_previously_quarantined_ean(self):
        row=good();row['listing_observed_at']=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat();row['detail_observed_at']=row['listing_observed_at']
        ingest([{**row,'price':None}],DSN)
        row['listing_observed_at']=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        result=sync_existing_prices([row],DSN)
        self.assertEqual((result['new_offers'],result['persisted_counts']['prices']),(1,1))
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select count(*) from quarantine_offers where resolved_at is null').fetchone()[0],0)
    def test_shared_bulk_default_keeps_existing_shop_policy_unchanged(self):
        from scripts.workers.price_database import update_existing
        row=good();ingest([row],DSN)
        update_existing('velvetdelft',[{'source_url':row['source_url'],'shop_domain':'velvetdelft.nl','price':'20.99','currency':'EUR','availability':'unknown'}],datetime.now(timezone.utc))
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select availability from prices').fetchone()[0],'in_stock')
    def test_old_retained_listing_is_excluded_from_new_price_cycle(self):
        row=good();row['listing_observed_at']=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat();ingest([row],DSN)
        retained={**row,'price':'0.99'}
        result=sync_existing_prices([retained],DSN,(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat())
        self.assertEqual(result['prices_written'],0)
        with psycopg.connect(DSN) as conn:self.assertEqual(float(conn.execute('select price from prices').fetchone()[0]),19.99)
    def test_committed_promotion_batch_survives_a_later_failure_and_retry(self):
        import json
        from scripts.scrapers.usf.jobs import velvetdelft_pipeline as pipeline
        data=json.loads((Path(__file__).parent/'fixtures/velvetdelft/sample100.json').read_text());rows=copy.deepcopy(data['records'])
        for row in rows:row.update(listing_observed_at=datetime.now(timezone.utc).isoformat(),detail_observed_at=datetime.now(timezone.utc).isoformat())
        original=pipeline.upsert_product;calls=0
        def fail_after_first_batch(*args):
            nonlocal calls
            calls+=1
            if calls==51:raise RuntimeError('Second promotion batch interrupted')
            return original(*args)
        with patch.object(pipeline,'upsert_product',side_effect=fail_after_first_batch):
            with self.assertRaises(RuntimeError):ingest(rows,DSN)
        with psycopg.connect(DSN) as conn:self.assertEqual(conn.execute('select count(*) from prices').fetchone()[0],50)
        retry=ingest(rows,DSN)
        self.assertEqual((retry['prices_written'],retry['persisted_counts']['prices']),(42,92))
        self.assertEqual(retry['raw_inserted'],0)
    def test_usf_preview_does_not_mutate_any_table(self):
        r=good();ingest([r],DSN)
        with psycopg.connect(DSN) as conn:
            tables=['scrape_runs','shop_product_links','raw_shop_scrapes','staged_offers','quarantine_offers','products','prices','price_history']
            before={t:conn.execute('select md5(coalesce(jsonb_agg(to_jsonb(t))::text,\'\')) from '+t+' t').fetchone()[0] for t in tables}
        preview([r])
        with psycopg.connect(DSN) as conn:
            after={t:conn.execute('select md5(coalesce(jsonb_agg(to_jsonb(t))::text,\'\')) from '+t+' t').fetchone()[0] for t in tables}
        self.assertEqual(before,after)

if __name__=='__main__':unittest.main()
