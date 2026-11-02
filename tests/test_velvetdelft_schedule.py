import copy
from datetime import datetime,timedelta,timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from scripts.workers.velvetdelft_schedule import plan,attempt,finish,selected_rows,restore,day
from scripts.scrapers.velvetdelft import DETAIL_REVISION,collect,save
from tests.test_velvetdelft import good

AT=datetime(2026,11,2,12,tzinfo=timezone.utc)


def state(count=1,verified=False):
    row=good()
    if not verified:row.update(ean='',gtin14='',ean_status='pending',detail_observed_at='',detail_parser_revision='',detail_next_at='')
    return {'version':1,'shop_id':'velvetdelft','records':{str(i):{**row,'source_product_id':str(i)} for i in range(count)},'categories':{},'requests':[]}


class ScheduleTests(unittest.TestCase):
    def test_initial_daily_budget_cannot_be_reset_by_restarting_the_workflow(self):
        s=state(1001)
        self.assertEqual(plan(s,AT)['limit'],1000)
        for row in list(s['records'].values())[:1000]:
            attempt(s,AT);row.update(detail_observed_at=AT.isoformat(),detail_parser_revision=DETAIL_REVISION)
        finish(s,'initial',1000,None,AT)
        self.assertFalse(plan(s,AT)['enabled'])
        tomorrow=plan(s,AT+timedelta(days=1))
        self.assertEqual((tomorrow['phase'],tomorrow['limit']),('initial',1))
    def test_initial_failures_are_attempted_once_before_switching_to_weekly(self):
        s=state(1000,verified=True)
        s['records']['1']['ean_status']='quarantine'
        finish(s,'initial',1000,None,AT)
        self.assertFalse(plan(s,AT+timedelta(days=6))['enabled'])
        weekly=plan(s,AT+timedelta(days=7))
        self.assertEqual((weekly['phase'],weekly['limit']),('maintenance',250))
        for _ in range(250):attempt(s,AT+timedelta(days=7))
        finish(s,'maintenance',250,None,AT+timedelta(days=7))
        self.assertFalse(plan(s,AT+timedelta(days=8))['enabled'])
        self.assertEqual(plan(s,AT+timedelta(days=14))['limit'],250)
    def test_interrupted_weekly_run_resumes_remaining_budget_not_another_250(self):
        s=state(1000,verified=True);finish(s,'initial',1000,None,AT)
        first=AT+timedelta(days=7);self.assertEqual(plan(s,first)['limit'],250)
        for _ in range(70):attempt(s,first)
        finish(s,'maintenance',70,'HTTP 429',first)
        self.assertEqual(plan(s,first+timedelta(days=1))['limit'],180)
    def test_weekly_checks_rotate_to_oldest_records(self):
        s=state(500,verified=True)
        for i,row in enumerate(s['records'].values()):row['detail_observed_at']=(AT+timedelta(seconds=i)).isoformat()
        first=selected_rows(s,'maintenance',250)
        for row in first:row['detail_observed_at']=(AT+timedelta(days=7)).isoformat()
        second=selected_rows(s,'maintenance',250)
        self.assertFalse({r['source_product_id'] for r in first}&{r['source_product_id'] for r in second})
    def test_initial_selection_does_not_retry_previously_checked_missing_eans(self):
        s=state(2);s['records']['0'].update(detail_observed_at=AT.isoformat(),detail_parser_revision=DETAIL_REVISION,ean_status='missing')
        self.assertEqual([r['source_product_id'] for r in selected_rows(s,'initial',1000)],['1'])
    def test_auto_wait_day_makes_no_site_requests(self):
        s=state(1,verified=True)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'state.json';save(p,s)
            with patch('scripts.scrapers.velvetdelft.Transport',side_effect=AssertionError('No website contact')):
                collect('details',p,automatic=True)
            self.assertEqual(json.loads(p.read_text())['automation']['last_run_checks'],0)
    def test_http_block_preserves_attempt_budget_and_next_record_checkpoint(self):
        s=state()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'state.json';save(p,s);client=Mock(requests=[]);client.get.side_effect=RuntimeError('HTTP 429; stopped')
            with self.assertRaises(RuntimeError):collect('details',p,detail_limit=1000,automatic=True,transport=client)
            saved=json.loads(p.read_text())
            self.assertEqual(saved['automation']['daily_checks'],1)
            self.assertFalse(saved['records']['0']['detail_observed_at'])
            self.assertIn('429',saved['automation']['last_run_error'])
    def test_newer_cache_can_recover_a_failed_durable_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'state.json';repo=Path(tmp)/'durable.gz'
            old=state();old['updated_at']='2026-11-01T00:00:00+00:00'
            fresh=copy.deepcopy(old);fresh['updated_at']='2026-11-02T00:00:00+00:00';fresh['automation']={'daily_checks':700}
            repo.write_bytes(gzip.compress(json.dumps(old).encode()));save(cache,fresh)
            with patch('scripts.workers.velvetdelft_schedule.CHECKPOINT',str(repo)):
                result=restore(cache)
            self.assertEqual(result['automation']['daily_checks'],700)
    def test_budget_day_uses_amsterdam_calendar_date(self):
        self.assertEqual(day(datetime(2026,11,2,23,30,tzinfo=timezone.utc)),'2026-11-03')

if __name__=='__main__':unittest.main()
