import contextlib
import copy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
import yaml

from scripts.workers import run_daily_ean as daily
from scripts.workers.ean_progress import GitHubProgress, day_key, initial_state, reserve, validate_state
from scripts.workers.ean_sources import BLOCKED, GREEN, EanSource


class Progress:
    def __init__(self, shop="everythingjazz"):
        self.state = initial_state(shop)
        self.saves = 0

    def load(self):
        return copy.deepcopy(self.state)

    def save(self, state):
        self.state = copy.deepcopy(state)
        self.saves += 1


class Queue:
    def __init__(self, total=250):
        self.rows = [{"id": str(i), "source_url": f"https://example.com/product/{i}", "payload": {}}
                     for i in range(total)]
        self.done, self.claimed, self.results = set(), set(), []

    def candidates(self, shop, limit):
        return [row for row in self.rows if row["id"] not in self.done | self.claimed][:limit]

    def fresh_catalog_rows(self, shop, rows):
        return [row for row in rows if row["id"] not in self.done]

    def register(self, shop, rows):
        known = {row["id"] for row in self.rows}
        self.rows.extend(row for row in rows if row["id"] not in known)

    def claim(self, shop, row):
        if row["id"] in self.done | self.claimed:
            return False
        self.claimed.add(row["id"])
        return True

    def finish(self, shop, row, result):
        self.claimed.discard(row["id"])
        self.done.add(row["id"])
        self.results.append(result)


class Source:
    def __init__(self, shop):
        self.events, self.fetched = [], []

    def close(self):
        pass

    def detail(self, row):
        self.fetched.append(row["source_url"])
        return {"ean": "00792755872161", "title": "Holiday Harmony", "domain": "example.com"}

    def catalog(self, cursor):
        return [], {**cursor, "exhausted": True}


class DailyEanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.patch = patch.object(daily, "Path", side_effect=lambda path: root / path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(lambda: self.stdout.__exit__(None, None, None))

    def test_two_days_fetch_next_hundred_without_overlap(self):
        progress, queue, sources = Progress(), Queue(), []
        def factory(shop):
            source = Source(shop)
            sources.append(source)
            return source
        first = daily.execute("everythingjazz", 100, True, progress=progress, queue=queue,
                              source_factory=factory, today="2026-10-18")
        second = daily.execute("everythingjazz", 100, True, progress=progress, queue=queue,
                               source_factory=factory, today="2026-10-19")
        self.assertEqual((first["attempted"], second["attempted"]), (100, 100))
        self.assertFalse(set(sources[0].fetched) & set(sources[1].fetched))
        self.assertTrue(sources[1].fetched[0].endswith("/100"))

    def test_manual_repeats_cannot_exceed_one_hundred_per_day(self):
        progress, queue = Progress(), Queue()
        results = [daily.execute("everythingjazz", limit, True, progress=progress, queue=queue,
                                source_factory=Source, today="2026-10-18") for limit in (60, 60, 100)]
        self.assertEqual([result["attempted"] for result in results], [60, 40, 0])
        self.assertEqual(results[-1]["outcome"], "daily_budget_exhausted")
        self.assertEqual(len(queue.done), 100)

    def test_dry_run_does_not_advance_or_claim(self):
        progress, queue = Progress(), Queue()
        before = copy.deepcopy(progress.state)
        result = daily.execute("everythingjazz", 5, False, progress=progress, queue=queue,
                               source_factory=Source, today="2026-10-18")
        self.assertEqual(result["attempted"], 5)
        self.assertEqual(progress.state, before)
        self.assertEqual(progress.saves, 0)
        self.assertFalse(queue.done | queue.claimed)

    def test_missing_ean_is_recorded_once_then_next_products(self):
        class Missing(Source):
            def detail(self, row):
                return {"ean": None}
        progress, queue = Progress(), Queue(4)
        first = daily.execute("everythingjazz", 2, True, progress=progress, queue=queue,
                              source_factory=Missing, today="2026-10-18")
        second = daily.execute("everythingjazz", 2, True, progress=progress, queue=queue,
                               source_factory=Source, today="2026-10-19")
        self.assertEqual(first["missing_ean"], 2)
        self.assertEqual([row["source_url"] for row in second["records"]],
                         ["https://example.com/product/2", "https://example.com/product/3"])

    def test_catalogue_cursor_survives_empty_worker_disk(self):
        class Pages(Source):
            def catalog(self, cursor):
                p = cursor["page"]
                return [{"id": str(p), "source_url": f"https://example.com/product/{p}", "payload": {}}], {"page": p+1, "seed": 0}
        progress, queue = Progress(), Queue(0)
        daily.execute("everythingjazz", 1, True, progress=progress, queue=queue,
                      source_factory=Pages, today="2026-10-18")
        self.assertEqual(progress.state["cursor"]["page"], 2)
        result = daily.execute("everythingjazz", 1, True, progress=progress, queue=queue,
                               source_factory=Pages, today="2026-10-19")
        self.assertEqual(result["records"][0]["source_url"], "https://example.com/product/2")

    def test_failed_checkpoint_prevents_source_requests(self):
        progress = Progress()
        progress.save = Mock(side_effect=RuntimeError("GitHub denied checkpoint write"))
        source = Mock()
        result = daily.execute("everythingjazz", 100, True, progress=progress, queue=Queue(), source_factory=source)
        source.assert_not_called()
        self.assertEqual(result["status"], "red")

    def test_403_stops_and_next_day_skips_already_attempted_product(self):
        class Blocked(Source):
            def detail(self, row):
                response = requests.Response()
                response.status_code = 403
                raise requests.HTTPError("HTTP 403", response=response)
        progress, queue = Progress(), Queue(101)
        first = daily.execute("everythingjazz", 100, True, progress=progress, queue=queue,
                              source_factory=Blocked, today="2026-10-18")
        self.assertEqual(first["attempted"], 1)
        self.assertEqual(first["technical_errors"], 1)
        self.assertEqual(first["missing_ean"], 0)
        second = daily.execute("everythingjazz", 1, True, progress=progress, queue=queue,
                               source_factory=Source, today="2026-10-19")
        self.assertTrue(second["records"][0]["source_url"].endswith("/1"))

    def test_budgets_use_amsterdam_day_instead_of_utc(self):
        self.assertEqual(day_key(datetime(2026, 10, 17, 22, 1, tzinfo=timezone.utc)), "2026-10-18")
        self.assertEqual(day_key(datetime(2026, 12, 17, 23, 1, tzinfo=timezone.utc)), "2026-12-18")

    def test_corrupt_progress_is_not_reset(self):
        state = initial_state("bobsvinyl")
        state["budget"]["reserved"] = 101
        with self.assertRaises(ValueError):
            validate_state(state, "bobsvinyl")

    def test_github_permission_failure_is_not_a_missing_checkpoint(self):
        store = GitHubProgress("bobsvinyl")
        with patch.object(store, "_api", side_effect=[{}, RuntimeError("HTTP 403")]):
            with self.assertRaises(RuntimeError):
                store.load()

    def test_only_approved_workflows_have_daily_schedules(self):
        root = Path(__file__).resolve().parents[1] / ".github/workflows"
        crons = set()
        for shop in GREEN:
            config = yaml.load((root / f"ean-detail-{shop}.yml").read_text(), Loader=yaml.BaseLoader)
            cron = config["on"]["schedule"][0]["cron"]
            self.assertNotIn(cron, crons)
            crons.add(cron)
            self.assertIn("'100'", config["jobs"]["worker"]["with"]["limit"])
            self.assertTrue(config["jobs"]["worker"]["uses"].endswith("_daily-ean-worker.yml"))
        self.assertEqual(len(crons), 26)
        for shop in BLOCKED:
            config = yaml.load((root / f"ean-detail-{shop}.yml").read_text(), Loader=yaml.BaseLoader)
            self.assertNotIn("schedule", config["on"])
            self.assertIn("GEBLOKKEERD", config["name"])


if __name__ == "__main__":
    unittest.main()
