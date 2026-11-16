import os
import unittest
from uuid import uuid4

import psycopg

from tests import test_price_database_postgres as dbtests
DSN = dbtests.DSN
from tests.test_variaworld_identity import record, OLD, NEW, EAN
from scripts.workers.price_database import _variaworld_stored_ean_matches, update_existing


class StoredVariaworldEvidenceTests(unittest.TestCase):
    class Cursor:
        def __init__(self, responses):
            self.responses = iter(responses)
            self.rows = []

        def execute(self, _query, _params):
            self.rows = next(self.responses)

        def fetchall(self):
            return self.rows

    def test_only_unambiguous_daily_ean_evidence_resolves(self):
        cursor = self.Cursor([
            [{"source_url": NEW, "eans": [EAN]}],
            [{"id": "product-one", "gtin_normalized": EAN.zfill(14)}],
        ])
        self.assertEqual(_variaworld_stored_ean_matches(cursor, [record()]),
                         {record()["source_url"].removeprefix("https://www."): "product-one"})

    def test_conflicting_source_eans_fail_closed(self):
        cursor = self.Cursor([[{"source_url": NEW, "eans": [EAN, "8719262039971"]}]])
        self.assertEqual(_variaworld_stored_ean_matches(cursor, [record()]), {})


@unittest.skipUnless(DSN, 'disposable loopback Postgres required')
class VariaworldPriceDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dbtests.PriceDatabaseTests.setUpClass.__func__(cls)
        with psycopg.connect(DSN) as conn:
            conn.execute('create table public.products(id uuid primary key,ean text,gtin_normalized text)')
            conn.execute('create table public.raw_shop_scrapes(source_url text,shop_id text,ean_raw text,payload jsonb)')

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DSN) as conn:
            conn.execute('drop table public.raw_shop_scrapes')
            conn.execute('drop table public.products')
        dbtests.PriceDatabaseTests.tearDownClass.__func__(cls)

    def setUp(self):
        dbtests.PriceDatabaseTests.setUp(self)
        with psycopg.connect(DSN) as conn:
            conn.execute('truncate public.products')
            conn.execute('truncate public.raw_shop_scrapes')
            conn.execute("update public.shops set domain='variaworld.nl' where id=%s", (self.shop,))

    def seed_varia(self, ean=EAN):
        identifier = uuid4()
        with psycopg.connect(DSN) as conn:
            conn.execute('insert into public.products values (%s,%s,%s)', (identifier, ean, ean.zfill(14)))
            conn.execute('insert into public.prices(product_id,shop_id,product_url,price,currency) values (%s,%s,%s,35.90,\'EUR\')',
                         (identifier, self.shop, OLD))
        return identifier

    def seed_evidence(self, ean=EAN, url=NEW):
        with psycopg.connect(DSN) as conn:
            conn.execute("insert into public.raw_shop_scrapes values (%s,'variaworld',%s,'{\"source\":\"curedplant_daily_ean\"}')",
                         (url, ean))

    def test_verified_replacement_updates_price_link_and_timestamp(self):
        identifier = self.seed_varia()
        self.seed_evidence()
        stats = update_existing('variaworld', [record()], self.started)
        self.assertEqual((stats['updated'], stats['verified']), (1, 1))
        with psycopg.connect(DSN) as conn:
            row = conn.execute('select price,product_url,last_seen_at from public.prices where product_id=%s', (identifier,)).fetchone()
            self.assertEqual((str(row[0]), row[1], row[2]), ('32.00', NEW, self.started))
            self.assertEqual(conn.execute('select count(*) from public.products').fetchone()[0], 1)

    def test_wrong_gtin_cannot_overwrite_existing_offer(self):
        self.seed_varia('8719262039971')
        self.seed_evidence()
        with self.assertRaisesRegex(RuntimeError, 'No existing prices'):
            update_existing('variaworld', [record()], self.started)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute('select product_url from public.prices').fetchone()[0], OLD)

    def test_duplicate_master_gtin_cannot_choose_an_arbitrary_product(self):
        self.seed_varia()
        self.seed_varia()
        self.seed_evidence()
        with self.assertRaisesRegex(RuntimeError, 'No existing prices'):
            update_existing('variaworld', [record()], self.started)

    def test_exact_ean_worker_evidence_can_create_first_variaworld_offer(self):
        identifier = uuid4()
        with psycopg.connect(DSN) as conn:
            conn.execute('insert into public.products values (%s,%s,%s)', (identifier, EAN, EAN.zfill(14)))
        self.seed_evidence()
        stats = update_existing('variaworld', [record()], self.started)
        self.assertEqual((stats['inserted'], stats['updated'], stats['verified']), (1, 1, 1))
        with psycopg.connect(DSN) as conn:
            row = conn.execute('select price,product_url from public.prices where product_id=%s', (identifier,)).fetchone()
            self.assertEqual((str(row[0]), row[1]), ('32.00', NEW))
