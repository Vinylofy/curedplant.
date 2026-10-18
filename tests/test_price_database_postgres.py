"""Opt-in price writes test: a disposable loopback Postgres is mandatory."""
from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
import psycopg

from scripts.workers.price_database import update_existing

DSN = os.environ.get("PRICE_TEST_DATABASE_URL")
SCHEMA = """
create table public.shops(id uuid primary key default gen_random_uuid(),domain text unique);
create table public.prices(product_id uuid default gen_random_uuid(),shop_id uuid,
 product_url text,price numeric,currency text default 'EUR',availability text default 'in_stock',
 last_seen_at timestamptz,updated_at timestamptz,is_active boolean default true,primary key(product_id,shop_id));
create table public.price_history(product_id uuid,shop_id uuid,price numeric,currency text,
 availability text,captured_at timestamptz,created_at timestamptz);
"""


@unittest.skipUnless(DSN, "set PRICE_TEST_DATABASE_URL to a disposable loopback DB")
class PriceDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlparse(DSN).hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Only disposable loopback Postgres is permitted")
        with psycopg.connect(DSN) as conn:
            conn.execute(SCHEMA)

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DSN) as conn:
            conn.execute("drop table public.price_history,public.prices,public.shops")

    def setUp(self):
        self.env = patch.dict(os.environ, {"DATABASE_URL": DSN})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.started = datetime.now(timezone.utc)
        with psycopg.connect(DSN) as conn:
            conn.execute("truncate public.price_history,public.prices,public.shops")
            self.shop = conn.execute("insert into public.shops(domain) values ('test.invalid') returning id").fetchone()[0]
            self.other = conn.execute("insert into public.shops(domain) values ('other.invalid') returning id").fetchone()[0]

    def seed(self, index, price=20, shop=None, last_seen=None):
        with psycopg.connect(DSN) as conn:
            return conn.execute("""insert into public.prices(shop_id,product_url,price,last_seen_at)
                values (%s,%s,%s,%s) returning product_id""", (shop or self.shop,
                f"https://www.test.invalid/record/{index}/?tracking=x", price, last_seen)).fetchone()[0]

    def records(self, count=1):
        return [{"source_url": f"https://test.invalid/record/{i}", "shop_domain": "test.invalid",
                 "price": "24.95", "currency": "EUR", "availability": "unknown"} for i in range(count)]

    def test_only_current_shop_existing_urls_are_updated_and_committed(self):
        self.seed(0)
        self.seed(0, price=99, shop=self.other)
        self.seed(2, price=33)
        stats = update_existing("test", self.records(2), self.started)
        self.assertEqual((stats["updated"], stats["verified"], stats["unmatched"]), (1, 1, 1))
        with psycopg.connect(DSN) as conn:
            rows = conn.execute("select price,availability from public.prices order by price").fetchall()
            self.assertEqual([(str(r[0]), r[1]) for r in rows], [("24.95", "in_stock"), ("33", "in_stock"), ("99", "in_stock")])
            self.assertEqual(conn.execute("select count(*) from public.price_history").fetchone()[0], 1)

    def test_currency_mismatch_rolls_back_the_whole_plan(self):
        self.seed(0)
        self.seed(1)
        records = self.records(2)
        records[1]["currency"] = "USD"
        with self.assertRaisesRegex(RuntimeError, "Currency mismatch"):
            update_existing("test", records, self.started)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute("select sum(price) from public.prices").fetchone()[0], 40)
            self.assertEqual(conn.execute("select count(*) from public.price_history").fetchone()[0], 0)

    def test_newer_prices_are_not_overwritten_and_zero_writes_cannot_pass(self):
        self.seed(0, last_seen=self.started + timedelta(seconds=1))
        with self.assertRaisesRegex(RuntimeError, "No existing prices updated"):
            update_existing("test", self.records(), self.started)

    def test_ambiguous_existing_variants_are_rejected(self):
        self.seed(0)
        self.seed(0, price=30)
        with self.assertRaisesRegex(RuntimeError, "variant review"):
            update_existing("test", self.records(), self.started)

    def test_isolated_ambiguous_url_is_quarantined_without_writing_its_products(self):
        for i in range(20):
            self.seed(i)
        self.seed(0, price=99)
        stats = update_existing("test", self.records(20), self.started)
        self.assertEqual((stats["updated"], stats["verified"]), (19, 19))
        self.assertEqual(stats["quarantined_urls"], ["https://test.invalid/record/0"])
        with psycopg.connect(DSN) as conn:
            prices = conn.execute("select price from public.prices where product_url like '%record/0/%' order by price").fetchall()
            self.assertEqual([str(r[0]) for r in prices], ["20", "99"])

    def test_unchanged_price_refresh_has_no_duplicate_history(self):
        self.seed(0, price="24.95")
        stats = update_existing("test", self.records(), self.started)
        self.assertEqual((stats["updated"], stats["changed"], stats["verified"]), (1, 0, 1))
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute("select count(*) from public.price_history").fetchone()[0], 0)

    def test_variaworld_query_article_ids_update_distinct_existing_prices(self):
        urls = ['https://www.variaworld.nl/artikel/detail.php?at=9077073000',
                'https://www.variaworld.nl/artikel/detail.php?at=9085033900']
        with psycopg.connect(DSN) as conn:
            shop = conn.execute("insert into public.shops(domain) values ('variaworld.nl') returning id").fetchone()[0]
            for url in urls:
                conn.execute("insert into public.prices(shop_id,product_url,price) values (%s,%s,10)", (shop,url))
        records = [dict(r, source_url=url, shop_domain='variaworld.nl', price=value)
                   for r,url,value in zip(self.records(2),urls,['24.95','39.90'])]
        stats = update_existing('variaworld', records, self.started)
        self.assertEqual(stats['verified'], 2)
        with psycopg.connect(DSN) as conn:
            actual = conn.execute('select price from public.prices where shop_id=%s order by product_url', (shop,)).fetchall()
        self.assertEqual([str(r[0]) for r in actual], ['24.95','39.90'])
