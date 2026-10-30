"""Optional integration test: exclusively a disposable database on localhost.

Set BOL_COVER_TEST_ADMIN_DSN to a local Postgres administrator DSN. Never point
this at Supabase. The test creates/drops only bol_cover_test_<random>.
"""
import json
import os
from pathlib import Path
import unittest
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from scripts.workers.bol_cover_fallback import validate
from tests.test_bol_cover_fallback import PRODUCT, RESPONSE


@unittest.skipUnless(os.environ.get('BOL_COVER_TEST_ADMIN_DSN'), 'local disposable Postgres not configured')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = conninfo_to_dict(os.environ['BOL_COVER_TEST_ADMIN_DSN'])
        if config.get('host') not in ('127.0.0.1', 'localhost', '::1'):
            raise RuntimeError('Only localhost test databases are allowed')
        cls.name = 'bol_cover_test_' + uuid.uuid4().hex
        cls.admin = psycopg.connect(os.environ['BOL_COVER_TEST_ADMIN_DSN'], autocommit=True)
        cls.admin.execute(sql.SQL('create database {}').format(sql.Identifier(cls.name)))
        cls.dsn = make_conninfo(os.environ['BOL_COVER_TEST_ADMIN_DSN'], dbname=cls.name)

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(sql.SQL('drop database {} with (force)').format(sql.Identifier(cls.name)))
        cls.admin.close()

    def test_migration_idempotence_locks_cache_quarantine_permissions_and_withdrawal(self):
        migration = (Path(__file__).resolve().parents[1] /
                     'supabase/migrations/20261030210000_bol_cover_fallback.sql').read_text()
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute('''create table public.products (
                id uuid primary key,ean text,gtin_normalized text,format_label text,title text,
                cover_status text default 'review', cover_url text,
                cover_storage_path text,cover_source_url text);
                create table public.product_cover_queue (
                product_id uuid unique references products(id), status text default 'review',
                last_error_code text default 'no_candidates', created_at timestamptz default now());
                create table public.product_cover_candidates (
                id uuid default gen_random_uuid(),product_id uuid,ean text,
                source_type text,source_rank integer,candidate_status text,
                is_selected boolean,image_url text,product_url text,last_error_code text,
                last_checked_at timestamptz);''')
            conn.execute(migration)
            conn.execute(migration)
            conn.execute('insert into products(id,ean,gtin_normalized,format_label) values (%s,%s,%s,%s)',
                         tuple(PRODUCT[k] for k in ('id','ean','gtin_normalized','format_label')))
            conn.execute('insert into product_cover_queue(product_id) values (%s)', (PRODUCT['id'],))
        with psycopg.connect(self.dsn) as first, psycopg.connect(self.dsn) as second:
            first.execute('set role bol_cover_worker')
            second.execute('set role bol_cover_worker')
            item = first.execute("select bol_cover_next('new',true,array[]::uuid[])").fetchone()[0]
            self.assertEqual(item['id'], PRODUCT['id'])
            self.assertIsNone(second.execute("select bol_cover_next('new',true,array[]::uuid[])").fetchone()[0])
            result = first.execute('select bol_cover_record(%s,%s::jsonb)',
                (PRODUCT['id'], json.dumps(validate(PRODUCT, RESPONSE)))).fetchone()[0]
            self.assertEqual(result, 1)
            first.commit()
            self.assertIsNone(second.execute("select bol_cover_next('new',true,array[]::uuid[])").fetchone()[0])
            second.rollback()
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            # Repeated direct record preserves a single rejected candidate.
            self.assertEqual(conn.execute('select bol_cover_record(%s,%s::jsonb)',
                (PRODUCT['id'], json.dumps(validate(PRODUCT, RESPONSE)))).fetchone()[0], 0)
            self.assertEqual(conn.execute('select count(*) from product_cover_candidates').fetchone()[0], 1)
            with self.assertRaises(psycopg.errors.CheckViolation):
                conn.execute("update product_cover_candidates set candidate_status='pending'")
            with self.assertRaises(psycopg.errors.CheckViolation):
                conn.execute("update product_cover_candidates set image_url='https://media.s-bol.com/x'")
            conn.execute("update products set cover_url='https://owned.test/existing'")
            self.assertEqual(conn.execute('select bol_cover_record(%s,%s::jsonb)',
                (PRODUCT['id'], json.dumps(validate(PRODUCT, RESPONSE)))).fetchone()[0], -1)
            self.assertFalse(conn.execute("select has_table_privilege('bol_cover_worker','products','UPDATE')").fetchone()[0])
            self.assertFalse(conn.execute("select has_table_privilege('bol_cover_worker','product_cover_queue','UPDATE')").fetchone()[0])
            # Operator removal is narrowly scoped and leaves a tombstone.
            conn.execute("delete from product_cover_candidates where product_id=%s and source_type='bol_affiliate'", (PRODUCT['id'],))
            conn.execute("update product_cover_queue set bol_result=null,bol_next_attempt_at='infinity' where product_id=%s", (PRODUCT['id'],))
            self.assertEqual(conn.execute('select count(*) from product_cover_candidates').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
