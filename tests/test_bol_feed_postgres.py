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

    def test_unchanged_price_on_new_day_has_no_duplicate_history(self):
        # Six-hour permitted source window straddling midnight.
        current = datetime(2026, 11, 7, 1, tzinfo=timezone.utc)
        first = current - timedelta(hours=2)
        plan = deepcopy(self.plan)
        plan["captured_at"] = first.isoformat()
        for offer in plan["offers"]:
            offer["captured_at"] = first.isoformat()
        with patch("scripts.importers.bol_feed.datetime") as clock:
            clock.fromisoformat = datetime.fromisoformat
            clock.now.return_value = current
            self.write(plan)
            plan["captured_at"] = current.isoformat()
            for offer in plan["offers"]:
                offer["captured_at"] = current.isoformat()
            self.write(plan)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute("select count(*) from public.price_history").fetchone()[0], 4)

    def test_batched_read_only_matching_compares_prices_and_detects_conflicts(self):
        self.write()
        review_matches(self.plan, self.dsn, self.shops, batch_size=1)
        self.assertEqual(self.plan["price_comparisons"]["unchanged_price"], 4)
        self.assertEqual(self.plan["existing_matches"], 2)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update public.products set format_label='CD'")
        review_matches(self.plan, self.dsn, self.shops, batch_size=1)
        self.assertEqual(len(self.plan["match_conflicts"]), 2)
        self.assertEqual(self.plan["existing_matches"], 0)

    def test_complete_feed_coverage_reports_missing_existing_shop_offers(self):
        self.write()
        plan = deepcopy(self.plan)
        plan["offers"] = plan["offers"][:2]
        review_matches(plan, self.dsn, self.shops, batch_size=1)
        for country in self.shops:
            coverage = plan["existing_offer_coverage"][country]
            self.assertEqual(coverage["existing_active_shop_offers"], 2)
            self.assertEqual(coverage["covered_by_feed"], 1)
            self.assertEqual(coverage["absent_from_eligible_feed"], 1)

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

    def test_writer_diagnostics_are_read_only(self):
        from scripts.importers.bol_feed import writer_diagnostics
        self.write()
        report = writer_diagnostics(self.dsn)
        self.assertEqual(report["status"], "writer_diagnosed")
        self.assertEqual(report["database_writes"], 0)
        self.assertTrue(report["product_lookup_plan"])
        with psycopg.connect(self.dsn) as conn:
            for table, count in [("products", 2), ("prices", 4), ("price_history", 4), ("raw_shop_scrapes", 4)]:
                self.assertEqual(conn.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()[0], count)

    def test_reviewed_pilot_recovery_uses_existing_writer_and_is_idempotent(self):
        from scripts.importers.bol_feed import main
        plan = deepcopy(self.plan)
        plan["offers"] = [o for o in plan["offers"] if o["country"] == "NL"]
        plan.update(status="blocked", errors=["QueryCanceled"], complete_feed=False, feed_sha256="a" * 64)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'review.json'; path.write_text(json.dumps(plan))
            output = Path(directory) / 'result.json'
            command = ['--profile', str(Path(__file__).parents[1] / 'config/bol-feed.live.json'),
                       '--review-plan', str(path), '--write', '--approve-publication',
                       '--expected-feed-sha256', 'a' * 64, '--output', str(output)]
            with patch.dict(os.environ, {'DATABASE_URL': self.dsn, 'BOL_SITE_ID': '12345',
                                       'BOL_SHOP_IDS': json.dumps({'NL': self.shops['NL']})}):
                self.assertEqual(main(command), 0)
                self.assertEqual(json.loads(output.read_text())["write_result"]["new_products"], 2)
                self.assertEqual(main(command), 0)
                self.assertEqual(json.loads(output.read_text())["database_writes"], 0)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('select count(*) from public.products').fetchone()[0], 2)
            self.assertEqual(conn.execute('select count(*) from public.price_history').fetchone()[0], 2)

    def test_catalogue_audit_classifies_missing_prices_without_writes(self):
        from scripts.workers.bol_feed_audit import audit_catalogue
        self.write()
        plan=deepcopy(self.plan);plan['feed_sha256']='test-snapshot'
        plan['offers']=plan['offers'][:2]
        with patch('scripts.workers.bol_feed_audit.SHOP_ID',self.shops['NL']):
            report=audit_catalogue(plan,self.dsn)
        self.assertEqual(report['database_writes'],0)
        self.assertEqual(report['counts']['active_shop_offers'],2)
        self.assertEqual(report['counts']['missing_api_eligible_frontend_visible'],1)
        self.assertEqual(report['api_sample'],[])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('select count(*) from public.price_history').fetchone()[0],4)

    def test_quarantined_format_conflict_preserves_canonical_product_and_old_prices(self):
        from scripts.importers.bol_feed import quarantine_identity_conflicts
        self.write()
        blocked=self.plan['offers'][0]['gtin']
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update public.products set format_label='CD' where gtin_normalized=%s",(blocked,))
        plan=deepcopy(self.plan);now=datetime.now(timezone.utc).isoformat();plan['captured_at']=now
        for offer in plan['offers']:offer.update(price='99.00',captured_at=now)
        review_matches(plan,self.dsn,self.shops);quarantine_identity_conflicts(plan)
        stats=self.write(plan)
        self.assertEqual(stats['updated_offers'],2)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('select format_label from public.products where gtin_normalized=%s',(blocked,)).fetchone()[0],'CD')
            self.assertEqual(conn.execute("select count(*) from public.prices pr join public.products p on p.id=pr.product_id where p.gtin_normalized=%s and pr.price=99",(blocked,)).fetchone()[0],0)

    def test_bulk_writer_uses_same_creation_history_and_replay_contracts(self):
        from scripts.importers.bol_feed import publish_batched
        result=publish_batched(self.plan,self.dsn,self.shops,approved=True,batch_products=1)
        self.assertEqual((result['new_products'],result['updated_offers'],result['committed_batches']),(2,4,2))
        again=publish_batched(self.plan,self.dsn,self.shops,approved=True,batch_products=1)
        self.assertEqual(again['updated_offers'],0)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('select count(*) from public.price_history').fetchone()[0],4)
            self.assertEqual(conn.execute('select count(*) from public.products where metadata_needs_review').fetchone()[0],2)

    def test_bulk_writer_preserves_newer_prices_and_rolls_back_failed_batch(self):
        self.write()
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update public.prices set price=88,last_seen_at=%s",(datetime.now(timezone.utc)+timedelta(hours=1),))
        result=publish(self.plan,self.dsn,self.shops,approved=True,bulk=True)
        self.assertEqual(result['skipped_newer'],4)
        fresh=deepcopy(self.plan);fresh['captured_at']=datetime.now(timezone.utc).isoformat()
        for offer in fresh['offers']:offer.update(price='99.00',captured_at=fresh['captured_at'])
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update public.prices set last_seen_at=now()-interval '1 hour'")
        with patch('scripts.importers.bol_feed.insert_history_rows',side_effect=RuntimeError('batch failure')):
            with self.assertRaises(RuntimeError):publish(fresh,self.dsn,self.shops,approved=True,bulk=True)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('select count(*) from public.prices where price=88').fetchone()[0],4)

    def test_bulk_writer_does_not_change_existing_masterdata(self):
        self.write()
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update public.products set title='Canonical',artist='MusicBrainz',cover_url='owned.webp'")
        newer=deepcopy(self.plan);newer['captured_at']=datetime.now(timezone.utc).isoformat()
        for offer in newer['offers']:offer.update(captured_at=newer['captured_at'],price='55.00')
        result=publish(newer,self.dsn,self.shops,approved=True,bulk=True)
        self.assertEqual(result['updated_offers'],4)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('select distinct title,artist,cover_url from public.products').fetchall(),[('Canonical','MusicBrainz','owned.webp')])

    def test_bulk_writer_bounds_round_trips_for_two_hundred_products(self):
        from scripts.importers.bol_feed import SafeWriterCursor
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'large.csv';demo.generate(path,count=200)
            plan=build_plan(path,PROFILE,['NL','BE'],'12345',limit=0)
        original=SafeWriterCursor.execute;calls=[]
        def observed(cursor,statement,params=None):
            calls.append(1);return original(cursor,statement,params)
        with patch.object(SafeWriterCursor,'execute',observed):
            result=publish(plan,self.dsn,self.shops,approved=True,bulk=True)
        self.assertEqual((result['new_products'],result['updated_offers']),(200,400))
        self.assertLess(len(calls),30)

    def test_bulk_writer_fails_before_mutation_when_other_bol_writer_holds_lock(self):
        with psycopg.connect(self.dsn) as locker:
            locker.execute("select pg_advisory_xact_lock(hashtextextended('bol-affiliate-import',0))")
            with self.assertRaisesRegex(FeedError,'bol_price_writer_busy'):
                publish(self.plan,self.dsn,self.shops,approved=True,bulk=True)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('select count(*) from public.products').fetchone()[0],0)

    def test_failed_later_batch_keeps_progress_without_false_full_success(self):
        from scripts.importers.bol_feed import publish_batched
        original=publish;calls=[]
        def second_fails(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise FeedError('injected_second_batch_failure')
            return original(*args,**kwargs)
        with patch('scripts.importers.bol_feed.publish',side_effect=second_fails):
            with self.assertRaisesRegex(FeedError,'second_batch'):
                publish_batched(self.plan,self.dsn,self.shops,approved=True,batch_products=1)
        self.assertEqual(self.plan['write_progress']['committed_batches'],1)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('select count(*) from public.products').fetchone()[0],1)
            self.assertEqual(conn.execute('select count(*) from public.prices').fetchone()[0],2)

    def test_module_entrypoint_handles_legacy_ineligible_rows_without_cross_module_errors(self):
        import subprocess,sys
        self.write()
        with psycopg.connect(self.dsn) as conn:
            conn.execute("update public.products set format_label='CD' where gtin_normalized=%s",(self.plan['offers'][0]['gtin'],))
        with tempfile.TemporaryDirectory() as directory:
            feed=Path(directory)/'feed.csv';demo.generate(feed,count=2)
            output=Path(directory)/'report.json'
            env=dict(os.environ,DATABASE_URL=self.dsn,BOL_SITE_ID='12345',BOL_SHOP_IDS=json.dumps(self.shops))
            result=subprocess.run([sys.executable,'-m','scripts.importers.bol_feed','--feed',str(feed),
                '--profile','config/bol-feed.live.json','--markets','NL,BE','--limit','0','--check-matches',
                '--output',str(output)],cwd=Path(__file__).parents[1],env=env,capture_output=True,text=True,timeout=30)
            report=json.loads(output.read_text())
            self.assertEqual((result.returncode,report['errors']),(0,[]))
            self.assertEqual(report['existing_offer_coverage']['NL']['required_current_offers'],1)
            self.assertEqual(report['quarantined_offers'],2)

    def test_database_failure_rolls_back_products_prices_and_evidence(self):
        with patch("scripts.importers.bol_feed.maybe_insert_history", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                self.write()
        with psycopg.connect(self.dsn) as conn:
            for table in ["products", "prices", "raw_shop_scrapes", "price_history"]:
                self.assertEqual(conn.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
