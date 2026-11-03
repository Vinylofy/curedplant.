"""Integration checks against an explicitly configured disposable database."""
import os
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import psycopg
from tests.test_rarevinyl_staging import record
from scripts.workers.rarevinyl_staging import write_raw

DSN = os.environ.get('RAREVINYL_TEST_DATABASE_URL')

@unittest.skipUnless(DSN, 'disposable test database not configured')
class RareVinylDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(DSN, autocommit=True)
        schema = Path('tests/fixtures/velvetdelft/usf-schema.sql').read_text()
        self.conn.execute(schema, prepare=False)
        self.conn.execute("delete from raw_shop_scrapes where shop_id='rarevinyl'")

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

if __name__ == '__main__': unittest.main()
