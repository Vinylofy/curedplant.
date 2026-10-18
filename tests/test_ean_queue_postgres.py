"""Opt-in queue integration tests; only a disposable loopback Postgres is allowed.

EAN_TEST_DATABASE_URL=postgresql://...@127.0.0.1:55432/postgres python -m unittest tests.test_ean_queue_postgres
The test creates and drops its own public queue tables. Never point at an app DB.
"""
import contextlib
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg

from scripts.workers.ean_queue import EanQueue

DSN = os.environ.get('EAN_TEST_DATABASE_URL')
SCHEMA = """
create table public.shop_product_links (
 id uuid primary key default gen_random_uuid(), shop_id text not null,
 source_url text not null, source_product_id text, first_seen_at timestamptz default now(),
 last_seen_at timestamptz default now(), last_detail_scraped_at timestamptz,
 last_price_refreshed_at timestamptz, status text default 'active', payload jsonb default '{}',
 ean_enrichment_status text default 'pending' check (ean_enrichment_status in ('pending','found','not_found','technical_error','not_applicable','second_hand_no_ean')),
 ean_next_attempt_at timestamptz, ean_last_result text,
 unique(shop_id,source_url)
);
create table public.raw_shop_scrapes (
 id uuid primary key default gen_random_uuid(), run_id uuid, shop_id text not null,
 source_url text not null, source_product_id text, title_raw text, ean_raw text,
 price_raw text, availability_raw text, image_url_raw text, payload jsonb,
 scraped_at timestamptz default now(), parse_status text default 'raw'
);
create table public.products (
 id uuid primary key default gen_random_uuid(), ean text unique,
 gtin_normalized text unique, artist text not null, title text not null,
 format_label text, cover_url text, canonical_key text, artist_normalized text,
 title_normalized text, search_text text, metadata_source text, metadata_status text,
 metadata_confidence numeric, metadata_needs_review boolean,
 created_at timestamptz default now(), updated_at timestamptz default now()
);
"""


@unittest.skipUnless(DSN, 'set EAN_TEST_DATABASE_URL to run disposable Postgres checks')
class QueuePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlparse(DSN).hostname not in {'127.0.0.1', 'localhost'}:
            raise ValueError('Integration tests require disposable loopback Postgres')
        with psycopg.connect(DSN) as conn:
            conn.execute(SCHEMA)

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DSN) as conn:
            conn.execute('drop table public.raw_shop_scrapes, public.shop_product_links, public.products')

    def setUp(self):
        @contextlib.contextmanager
        def connection():
            with psycopg.connect(DSN) as conn:
                yield conn
        self.connection_patch = patch('scripts.workers.ean_queue.db_connection', connection)
        self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.queue = EanQueue()
        with psycopg.connect(DSN) as conn:
            conn.execute('truncate public.raw_shop_scrapes, public.shop_product_links, public.products')

    def seed(self, count=250):
        rows = [{'source_url': f'https://test.invalid/product/{i}', 'payload': {'title': 'Test record', 'artist': 'Test artist', 'price': '25.00'}} for i in range(count)]
        self.queue.register('testshop', rows)
        return rows

    def test_two_hundred_distinct_records_and_metadata_only_writes(self):
        rows = self.seed()
        first = self.queue.candidates('testshop', 100)
        with patch('scripts.workers.ean_queue.upsert_product') as product:
            for row in first:
                self.assertTrue(self.queue.claim('testshop', row))
                self.assertFalse(self.queue.claim('testshop', row))
                self.queue.finish('testshop', row, {'ean': '00792755872161', 'title': 'Holiday Harmony', 'domain': 'test.invalid'})
            self.assertEqual(product.call_count, 100)
        # Rediscovery preserves completed state, despite a listing price.
        self.queue.register('testshop', rows)
        second = self.queue.candidates('testshop', 100)
        self.assertEqual(len(second), 100)
        self.assertFalse({r['id'] for r in first} & {r['id'] for r in second})
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select count(*) from public.raw_shop_scrapes where price_raw is null and availability_raw is null').fetchone()[0], 100)
            self.assertEqual(conn.execute('select count(*) from public.shop_product_links where last_price_refreshed_at is not null').fetchone()[0], 0)

    def test_misses_and_errors_are_done_and_raw_existing_ean_is_skipped(self):
        rows = self.seed(4)
        selected = self.queue.candidates('testshop', 4)
        self.queue.claim('testshop', selected[0])
        self.queue.finish('testshop', selected[0], {'ean': None})
        self.queue.claim('testshop', selected[1])
        self.queue.finish('testshop', selected[1], {'ean': None, 'error': 'HTTP 403'})
        with psycopg.connect(DSN) as conn:
            conn.execute('insert into public.raw_shop_scrapes (shop_id,source_url,ean_raw) values (%s,%s,%s)', ('testshop',selected[2]['source_url'],'00792755872161'))
        self.assertEqual([r['id'] for r in self.queue.candidates('testshop', 100)], [selected[3]['id']])
        self.assertEqual([r['source_url'] for r in self.queue.fresh_catalog_rows('testshop', rows)], [selected[3]['source_url']])

    def test_unfinished_claim_recovers_after_lease_expiry(self):
        self.seed(1)
        row = self.queue.candidates('testshop', 1)[0]
        self.assertTrue(self.queue.claim('testshop', row))
        self.assertEqual(self.queue.candidates('testshop', 1), [])
        with psycopg.connect(DSN) as conn:
            conn.execute("update public.shop_product_links set ean_next_attempt_at=now()-interval '1 second'")
        self.assertEqual(self.queue.candidates('testshop', 1)[0]['id'], row['id'])

    def test_failed_product_upsert_rolls_back_done_and_raw_ean(self):
        self.seed(1)
        row = self.queue.candidates('testshop', 1)[0]
        self.assertTrue(self.queue.claim('testshop', row))
        with patch('scripts.workers.ean_queue.upsert_product', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):
                self.queue.finish('testshop', row, {'ean': '00792755872161', 'title': 'Test', 'domain': 'test.invalid'})
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select count(*) from public.raw_shop_scrapes').fetchone()[0], 0)
            self.assertIsNone(conn.execute('select last_detail_scraped_at from public.shop_product_links').fetchone()[0])

    def test_incomplete_imusic_identity_preserves_raw_ean_without_canonical_write(self):
        self.seed(1)
        row = self.queue.candidates('testshop', 1)[0]
        row['payload'] = {}
        self.queue.claim('testshop', row)
        with patch('scripts.workers.ean_queue.upsert_product') as product:
            self.queue.finish('testshop', row, {'ean': '00603497810826', 'title': 'Love (LP)', 'domain': 'imusic.nl'})
            product.assert_not_called()
        with psycopg.connect(DSN) as conn:
            saved = conn.execute('select ean_raw, payload from public.raw_shop_scrapes').fetchone()
            self.assertEqual(saved[0], '00603497810826')
            self.assertEqual(saved[1]['metadata_deferred'], 'missing_artist')
            self.assertEqual(conn.execute('select ean_enrichment_status from public.shop_product_links').fetchone()[0], 'found')

    def test_imusic_real_canonical_upsert_fills_blank_artist_without_null_error(self):
        self.queue.register('imusic', [{'source_url': 'https://imusic.nl/music/0603497810826', 'payload': {}}])
        row = self.queue.candidates('imusic', 1)[0]
        with psycopg.connect(DSN) as conn:
            conn.execute("insert into public.products (ean,gtin_normalized,artist,title) values ('0603497810826','00603497810826','','Love (LP)')")
        self.queue.claim('imusic', row)
        self.queue.finish('imusic', row, {'ean': '00603497810826', 'artist': 'Love', 'title': 'Love (LP)', 'domain': 'imusic.nl'})
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select artist,title from public.products').fetchall(), [('Love','Love (LP)')])
            self.assertEqual(conn.execute('select ean_enrichment_status from public.shop_product_links').fetchone()[0], 'found')

    def test_removed_product_completes_queue_as_not_applicable(self):
        self.seed(1)
        row = self.queue.candidates('testshop', 1)[0]
        self.queue.claim('testshop', row)
        self.queue.finish('testshop', row, {'ean': None, 'unavailable': True, 'http_status': 404})
        self.assertEqual(self.queue.candidates('testshop', 1), [])
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select ean_enrichment_status from public.shop_product_links').fetchone()[0], 'not_applicable')

    def test_fifties_requeue_is_scoped_to_old_false_misses_and_idempotent(self):
        from psycopg.types.json import Jsonb
        for i, (shop, day, version) in enumerate([
            ('fiftiesstore','2026-10-18',None), ('fiftiesstore','2026-10-18',2),
            ('fiftiesstore','2026-10-17',None), ('bobsvinyl','2026-10-18',None)]):
            result = {'day': day, 'detail_sha256': 'source-proof', 'ean': None}
            if version: result['ean_parser_version'] = version
            with psycopg.connect(DSN) as conn:
                conn.execute("insert into public.shop_product_links (shop_id,source_url,last_detail_scraped_at,ean_enrichment_status,payload) values (%s,%s,now(),'not_found',%s)", (shop,f'https://test.invalid/{i}',Jsonb({'curedplant_daily_ean':result})))
        self.assertEqual(self.queue.requeue_fifties_layout_misses(), 1)
        self.assertEqual(self.queue.requeue_fifties_layout_misses(), 0)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select source_url from public.shop_product_links where last_detail_scraped_at is null').fetchall(), [('https://test.invalid/0',)])
            self.assertEqual(conn.execute("select payload->'curedplant_daily_ean'->>'detail_sha256' from public.shop_product_links where source_url='https://test.invalid/0'").fetchone()[0], 'source-proof')
