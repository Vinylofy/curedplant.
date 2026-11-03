"""Integration checks against an explicitly configured disposable database."""
import os
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from pathlib import Path
import psycopg
from tests.test_rarevinyl_staging import record
from scripts.workers.rarevinyl_staging import write_raw, checkpoint_page
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

if __name__ == '__main__': unittest.main()
