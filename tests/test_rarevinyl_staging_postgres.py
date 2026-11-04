"""Integration checks against an explicitly configured disposable database."""
import os
import json
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from pathlib import Path
import psycopg
from tests.test_rarevinyl_staging import record
from scripts.workers.rarevinyl_staging import write_raw, checkpoint_page, ingest_capture, pending_details, persist_detail, register_shop
from scripts.workers.rarevinyl_prices import sync_existing

DSN = os.environ.get('RAREVINYL_TEST_DATABASE_URL')

@unittest.skipUnless(DSN, 'disposable test database not configured')
class RareVinylDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(DSN, autocommit=True)
        schema = Path('tests/fixtures/velvetdelft/usf-schema.sql').read_text()
        self.conn.execute(schema, prepare=False)
        self.conn.execute("delete from raw_shop_scrapes where shop_id='rarevinyl'")
        self.conn.execute("create table if not exists rarevinyl_source_checkpoint(name text primary key,next_page integer not null,cycle_complete boolean not null default false,last_page_signature text,updated_at timestamptz default now())")
        self.conn.execute("delete from rarevinyl_source_checkpoint")
        self.conn.execute("delete from shop_product_links where shop_id='rarevinyl'")

    def tearDown(self):
        self.conn.close()

    def test_idempotent_and_changed_price(self):
        source = record(observed_at=datetime.now(timezone.utc).isoformat())
        self.assertEqual(write_raw(self.conn, [source])['inserted'], 1)
        self.assertEqual(write_raw(self.conn, [source])['reused'], 1)
        self.assertEqual(write_raw(self.conn, [source | {'price':'30.00'}])['inserted'], 1)
        self.assertEqual(self.conn.execute("select count(*) from raw_shop_scrapes where shop_id='rarevinyl'").fetchone()[0], 2)

    def test_stale_and_invalid_batch_roll_back(self):
        source = record(observed_at=datetime.now(timezone.utc).isoformat())
        stale = record(url='https://eu.rarevinyl.com/products/other', source_id='456',
                       observed_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())
        with self.assertRaises(ValueError): write_raw(self.conn, [source, stale])
        self.assertEqual(self.conn.execute("select count(*) from raw_shop_scrapes where shop_id='rarevinyl'").fetchone()[0], 0)
        with self.assertRaises(ValueError): write_raw(self.conn, [source, source])

    def test_page_checkpoint_resume_and_conflict_rollback(self):
        source = record(observed_at=datetime.now(timezone.utc).isoformat())
        self.assertEqual(checkpoint_page(self.conn, 1, [source])['next_page'], 2)
        with self.assertRaises(ValueError): checkpoint_page(self.conn, 1, [source])
        with self.assertRaisesRegex(ValueError, 'repeated_listing_page'): checkpoint_page(self.conn, 2, [source])
        other = record(url='https://eu.rarevinyl.com/products/other', source_id='456', observed_at=source['observed_at'])
        conflict = source | {'source_id':'789'}
        with self.assertRaises(ValueError): checkpoint_page(self.conn, 2, [other, conflict])
        self.assertEqual(self.conn.execute("select next_page from rarevinyl_source_checkpoint where name='discovery'").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("select count(*) from shop_product_links where shop_id='rarevinyl'").fetchone()[0], 1)
        self.assertEqual(checkpoint_page(self.conn, 2, [], end_of_catalogue=True)['cycle_complete'], True)
        with self.assertRaises(ValueError): checkpoint_page(self.conn, 2, [], end_of_catalogue=True)

    def test_capture_raw_and_page_commit_or_rollback_together(self):
        source = record(observed_at=datetime.now(timezone.utc).isoformat())
        capture = {'status':'research_only','database_writes':0,'publication_blocked':True,
                   'start_page':1,'end_of_catalogue':False,'records':[source],
                   'summary':{'discovered':1},'errors':[]}
        result = ingest_capture(self.conn, capture)
        self.assertEqual(result['raw']['inserted'],1)
        self.assertEqual(result['checkpoint']['next_page'],2)
        newer = source | {'price':'31.00'}
        with self.assertRaisesRegex(ValueError,'checkpoint_page_mismatch'):
            ingest_capture(self.conn, capture | {'records':[newer]})
        self.assertEqual(self.conn.execute("select count(*) from raw_shop_scrapes where shop_id='rarevinyl'").fetchone()[0],1)

    def test_detail_queue_preserves_identity_and_rejects_changed_listing(self):
        current = datetime.now(timezone.utc).isoformat()
        source = record(observed_at=current,variant_id='22',sealed_candidate=True)
        checkpoint_page(self.conn, 1, [source])
        self.assertEqual(len(pending_details(self.conn,10)),1)
        detail = source | {'detail_checked_at':current,'condition_evidence':'Factory sealed from new. This item is unplayed.'}
        with self.assertRaisesRegex(ValueError,'listing_changed'):
            persist_detail(self.conn, detail | {'price':'999.00'})
        self.assertEqual(self.conn.execute("select count(*) from raw_shop_scrapes where shop_id='rarevinyl'").fetchone()[0],0)
        result = persist_detail(self.conn,detail)
        self.assertEqual(result['route'],'ean_staging')
        self.assertEqual(len(pending_details(self.conn,10)),0)
        self.assertEqual(self.conn.execute("select count(*) from raw_shop_scrapes where shop_id='rarevinyl'").fetchone()[0],1)

    def test_existing_price_write_is_scoped_and_verified(self):
        self.conn.execute('create table if not exists shops(id uuid primary key default gen_random_uuid(),domain text unique)')
        self.conn.execute("""create table if not exists prices(product_id uuid default gen_random_uuid(),shop_id uuid,
          product_url text,price numeric,currency text,availability text,last_seen_at timestamptz,
          updated_at timestamptz,is_active boolean default true,primary key(product_id,shop_id))""")
        self.conn.execute('create table if not exists price_history(product_id uuid,shop_id uuid,price numeric,currency text,availability text,captured_at timestamptz,created_at timestamptz)')
        self.conn.execute('truncate price_history, prices, shops')
        shop = self.conn.execute("insert into shops(domain) values('eu.rarevinyl.com') returning id").fetchone()[0]
        url = 'https://eu.rarevinyl.com/products/example'
        self.conn.execute("insert into prices(shop_id,product_url,price,currency,availability) values(%s,%s,20,'EUR','in_stock')", (shop,url))
        current = datetime.now(timezone.utc).isoformat()
        source = record(observed_at=current,detail_checked_at=current,currency='EUR',
                        condition_evidence='Factory sealed from new. This item is unplayed.')
        with patch.dict(os.environ, {'DATABASE_URL':DSN}):
            result = sync_existing([source], write=True)
        self.assertEqual((result['writer']['updated'], result['writer']['verified']), (1,1))
        self.assertEqual(str(self.conn.execute('select price from prices').fetchone()[0]), '29.95')
        self.assertEqual(self.conn.execute('select count(*) from price_history').fetchone()[0], 1)

    def test_registration_is_idempotent_and_does_not_reactivate(self):
        self.conn.execute('create table if not exists shops(id uuid primary key default gen_random_uuid(),domain text unique)')
        self.conn.execute('alter table shops add column if not exists name text, add column if not exists country text, add column if not exists is_active boolean')
        self.conn.execute('truncate shops')
        self.assertTrue(register_shop(self.conn)['created'])
        self.assertFalse(register_shop(self.conn)['created'])
        self.conn.execute("update shops set is_active=false where domain='eu.rarevinyl.com'")
        with self.assertRaisesRegex(ValueError,'existing_shop_requires_review'): register_shop(self.conn)
        self.assertFalse(self.conn.execute("select is_active from shops where domain='eu.rarevinyl.com'").fetchone()[0])

    @unittest.skipUnless(os.environ.get('RAREVINYL_LIVE_CAPTURE'), 'live source capture not supplied')
    def test_fresh_real_capture_enters_source_registry(self):
        capture = json.loads(Path(os.environ['RAREVINYL_LIVE_CAPTURE']).read_text())
        result = ingest_capture(self.conn,capture)
        self.assertEqual(result['checkpoint']['retained'],capture['summary']['discovered'])
        self.assertGreater(result['raw']['inserted'],0)
        self.assertGreater(result['pending_detail'],0)
        self.assertEqual(self.conn.execute("select count(*) from shop_product_links where shop_id='rarevinyl'").fetchone()[0],capture['summary']['discovered'])

if __name__ == '__main__': unittest.main()
