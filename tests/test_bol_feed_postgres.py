"""Integration tests create/drop ONLY their own temporary loopback database."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg.conninfo import make_conninfo, conninfo_to_dict
from psycopg import sql

from scripts.importers.bol_feed import FeedError, build_plan, publish, review_matches
from test_bol_feed import demo, PROFILE

DSN = os.environ.get("BOL_TEST_DATABASE_URL")
SCHEMA = """
create table public.shops(id uuid primary key default gen_random_uuid(),name text,country text);
create table public.shop_shipping_destinations(shop_id uuid,country_code text,status text);
create table public.products(id uuid primary key default gen_random_uuid(),ean text unique,
 gtin_normalized text unique,artist text,title text,format_label text,cover_url text,
 canonical_key text,artist_normalized text,title_normalized text,search_text text,
 metadata_source text,metadata_status text,metadata_confidence numeric,metadata_needs_review boolean,
 created_at timestamptz,updated_at timestamptz);
create table public.prices(product_id uuid references public.products(id),shop_id uuid,
 price numeric,currency text,product_url text,availability text,first_seen_at timestamptz,
 last_seen_at timestamptz,is_active boolean,ean_raw text,gtin_normalized text,
 created_at timestamptz,updated_at timestamptz,primary key(product_id,shop_id));
create table public.price_history(product_id uuid,shop_id uuid,price numeric,currency text,
 availability text,captured_at timestamptz,created_at timestamptz);
create table public.raw_shop_scrapes(id uuid primary key default gen_random_uuid(),shop_id text,
 source_url text,source_product_id text,title_raw text,ean_raw text,price_raw text,
 availability_raw text,payload jsonb,scraped_at timestamptz,parse_status text);
"""


@unittest.skipUnless(DSN, "set BOL_TEST_DATABASE_URL to a disposable loopback Postgres")
class BolPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if conninfo_to_dict(DSN).get("host") not in {"127.0.0.1", "localhost"}:
            raise ValueError("Loopback disposable test database required")
        cls.dbname = "bol_test_" + uuid.uuid4().hex
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("create database {}").format(sql.Identifier(cls.dbname)))
        cls.dsn = make_conninfo(DSN, dbname=cls.dbname)
        with psycopg.connect(cls.dsn) as conn:
            conn.execute(SCHEMA)

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("drop database {}").format(sql.Identifier(cls.dbname)))

    def setUp(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute("truncate public.raw_shop_scrapes,public.price_history,public.prices,public.products,public.shop_shipping_destinations,public.shops cascade")
            self.shops = {}
            for country in ["NL", "BE"]:
                self.shops[country] = str(conn.execute(
                    "insert into public.shops(name,country) values (%s,%s) returning id",
                    ("bol " + country, country)).fetchone()[0])
                conn.execute("insert into public.shop_shipping_destinations values (%s,%s,'confirmed')",
                             (self.shops[country], country))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.csv"; demo.generate(path, count=2)
            self.plan = build_plan(path, PROFILE, ["NL", "BE"], "12345", limit=0)

    def write(self, plan=None):
        return publish(plan or self.plan, self.dsn, self.shops, approved=True)

    def test_two_markets_share_products_but_prices_are_separate_and_verified(self):
        stats = self.write()
        self.assertEqual((stats["new_products"], stats["updated_offers"], stats["committed_verified"]), (2, 4, 4))
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from public.products").fetchone()[0], 2)
            rows = conn.execute("select payload->>'country',payload->>'shipping_status' from public.raw_shop_scrapes").fetchall()
            self.assertEqual({r[0] for r in rows}, {"NL", "BE"})

    def test_identical_replay_has_no_extra_offers_history_or_raw_data(self):
        self.write(); stats = self.write()
        self.assertEqual(stats["updated_offers"], 0)
        with psycopg.connect(self.dsn) as conn:
            for table, count in [("prices", 4), ("price_history", 4), ("raw_shop_scrapes", 4)]:
                self.assertEqual(conn.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()[0], count)

    def test_newer_existing_price_and_other_market_are_preserved(self):
        self.write()
        changed = deepcopy(self.plan); changed["offers"] = [changed["offers"][0]]
        changed["offers"][0]["price"] = "1.00"
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update public.prices set price=99,last_seen_at=%s where shop_id=%s",
                         (datetime.now(timezone.utc) + timedelta(hours=1), self.shops["NL"]))
        stats = self.write(changed)
        self.assertEqual(stats["skipped_newer"], 1)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from public.prices where price=99").fetchone()[0], 2)
            self.assertEqual(conn.execute("select count(*) from public.prices where shop_id=%s", (self.shops["BE"],)).fetchone()[0], 2)

    def test_existing_masterdata_unchanged_and_matches_are_read_only(self):
        self.write()
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update public.products set title='Canonical MusicBrainz title',cover_url='owned.webp'")
        review_matches(self.plan, self.dsn)
        self.assertEqual((self.plan["existing_matches"], self.plan["new_products"]), (2, 0))
        self.write()
        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute("select distinct title,cover_url from public.products").fetchall()
            self.assertEqual(rows, [('Canonical MusicBrainz title', 'owned.webp')])

    def test_cd_barcode_conflict_rolls_back_both_countries(self):
        self.write()
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update public.products set format_label='CD'")
        with self.assertRaisesRegex(FeedError, "format_conflict"):
            self.write()
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from public.price_history").fetchone()[0], 4)

    def test_cross_market_visibility_and_wrong_shop_ids_rejected(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute("insert into public.shop_shipping_destinations values (%s,'BE','confirmed')",
                         (self.shops["NL"],))
        with self.assertRaisesRegex(FeedError, "cross_market"):
            self.write()
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from public.products").fetchone()[0], 0)

    def test_empty_failed_or_stale_plans_never_deactivate_existing_offers(self):
        self.write()
        for change in [{"offers": []}, {"errors": ["truncated_feed"]},
                       {"captured_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}]:
            p = deepcopy(self.plan); p.update(change)
            with self.assertRaises(FeedError):
                self.write(p)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from public.prices where is_active").fetchone()[0], 4)

    def test_database_failure_rolls_back_products_prices_and_evidence(self):
        with patch("scripts.importers.bol_feed.maybe_insert_history", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                self.write()
        with psycopg.connect(self.dsn) as conn:
            for table in ["products", "prices", "raw_shop_scrapes", "price_history"]:
                self.assertEqual(conn.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
