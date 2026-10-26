import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

import requests

from scripts.workers import jpc_price_source as source
from scripts.scrapers.usf.jobs import discover_jpc_vinyl as native


class Process:
    def __init__(self, code=0):
        self.returncode = code
    def poll(self):
        return self.returncode
    def wait(self, **kwargs):
        return self.returncode


class JpcPriceSourceTests(unittest.TestCase):
    def setUp(self):
        indexed = patch.object(source, "route_specs", return_value="rock=https://www.jpc.de/s/1238692_66733?searchtype=cid")
        indexed.start()
        self.addCleanup(indexed.stop)

    def test_two_native_price_shards_cover_all_page_residues_without_writes(self):
        for index in range(source.SHARDS):
            command = source.command_for(index,0)
            self.assertIn('scripts.scrapers.usf.jobs.discover_jpc_vinyl', command)
            self.assertNotIn('--write',command)
            self.assertEqual(command[command.index('--delay')+1], '4.0')
            self.assertEqual(command[command.index('--listing-page-shard-index')+1],str(index))
            self.assertEqual(command[command.index('--listing-page-shard-count')+1],str(source.SHARDS))
            self.assertEqual(command[command.index('--max-pages-per-route')+1],'0')

    def test_combines_both_read_only_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'records.jsonl'
            target.write_text('')
            def spawn(command, **kwargs):
                self.assertNotIn('--include-route-index', command)
                self.assertEqual(kwargs['env']['DATABASE_URL'],'')
                self.assertTrue(kwargs['env']['CUREDPLANT_JPC_COOLDOWN'].endswith('/cooldown'))
                index=command[command.index('--listing-page-shard-index')+1]
                Path(kwargs['env']['CUREDPLANT_PRICE_EVIDENCE']).write_text(json.dumps({'source_url':f'https://jpc.de/hnum/{index}','price':'24.99'})+'\n')
                return Process()
            with patch.dict(os.environ,{'CUREDPLANT_PRICE_EVIDENCE':str(target),'DATABASE_URL':'never-pass-this'}), \
                 patch.object(source.subprocess,'Popen',side_effect=spawn), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(source.run(0),0)
            self.assertEqual(len(target.read_text().splitlines()),source.SHARDS)

    def test_a_failed_shard_cannot_yield_a_partial_green(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'records.jsonl'
            target.write_text('')
            with patch.dict(os.environ,{'CUREDPLANT_PRICE_EVIDENCE':str(target)}), \
                 patch.object(source.subprocess,'Popen',side_effect=[Process(0),Process(1)]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(source.run(0),1)
            records=[json.loads(line) for line in target.read_text().splitlines()]
            self.assertEqual(records[-1]['kind'],'source_error')

    def test_429_and_access_denials_stop_all_parts(self):
        self.assertIsNotNone(source.blocked_log('[JPC-DISCOVER-RATE-LIMIT] blocked'))
        self.assertIsNotNone(source.blocked_log("[JPC-DISCOVER-HTTP-SKIP] {'status_code': 403}"))
        self.assertIsNone(source.blocked_log("[JPC-DISCOVER-HTTP-SKIP] {'status_code': 404}"))

    def test_server_errors_are_not_normal_catalogue_end(self):
        for status in [400, 401, 403, 429, 500, 502, 503, 504]:
            with self.subTest(status=status):
                self.assertIsNotNone(source.blocked_log(
                    f"[JPC-DISCOVER-HTTP-SKIP] {{'status_code': {status}}}"))

    def test_http_error_log_from_successful_process_still_blocks_partial_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'records.jsonl'
            target.write_text('')
            def spawn(command, **kwargs):
                kwargs['stdout'].write("[JPC-DISCOVER-HTTP-SKIP] {'status_code': 503}\n")
                kwargs['stdout'].flush()
                Path(kwargs['env']['CUREDPLANT_PRICE_EVIDENCE']).write_text(
                    json.dumps({'source_url': 'https://jpc.de/album', 'price': '24.95'}) + '\n')
                return Process()
            with patch.dict(os.environ, {'CUREDPLANT_PRICE_EVIDENCE': str(target)}), \
                 patch.object(source.subprocess, 'Popen', side_effect=spawn), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(source.run(0), 1)
            records = [json.loads(line) for line in target.read_text().splitlines()]
            self.assertEqual(records[-1]['kind'], 'source_error')


class JpcPaginationTests(unittest.TestCase):
    route = native.RouteSpec('test', 'https://www.jpc.de/s/1238692_66733?searchtype=cid')

    def response(self, products=(), status=200):
        response = requests.Response()
        response.status_code = status
        response.url = self.route.url
        response.encoding = 'utf-8'
        response._content = ''.join(
            f'<div><a href="/jpcng/poprock/detail/-/art/album/hnum/{identifier}">Artist Album LP</a>'
            f'<p>EUR 24,99 Aktueller Preis</p><p>{availability}</p></div>'
            for identifier, availability in products).encode()
        return response

    def discover(self, responses):
        with patch.object(native, 'build_session', return_value=Mock()), \
             patch.object(native, 'request_listing_page', side_effect=responses) as fetch, \
             contextlib.redirect_stdout(io.StringIO()):
            links = native.discover_links(routes=[self.route], include_route_index=False,
                max_pages_per_route=0, pagination_fallback='ff', delay_seconds=0,
                timeout_seconds=10, availability_filter='none')
        return links, fetch.call_count

    def test_unavailable_page_does_not_hide_next_in_stock_page(self):
        links, requests_made = self.discover([
            self.response([('111', 'lieferbar innerhalb 2 Wochen')]),
            self.response([('222', 'Artikel am Lager')]), self.response()])
        self.assertEqual(requests_made, 3)
        self.assertEqual([link.source_product_id for link in links], ['222'])

    def test_same_eligible_subset_does_not_mean_repeated_source_page(self):
        links, requests_made = self.discover([
            self.response([('111', 'Artikel am Lager'), ('222', 'nicht lieferbar')]),
            self.response([('111', 'Artikel am Lager'), ('333', 'nicht lieferbar')]),
            self.response([('444', 'Artikel am Lager')]), self.response()])
        self.assertEqual(requests_made, 4)
        self.assertEqual({link.source_product_id for link in links}, {'111', '444'})

    def test_repeated_unavailable_page_still_terminates(self):
        response = self.response([('111', 'nicht lieferbar')])
        links, requests_made = self.discover([response, response])
        self.assertEqual((links, requests_made), ([], 2))

    def test_http_and_network_failures_cannot_return_partial_success(self):
        for error in [self.response(status=503), self.response(status=403),
                      self.response(status=429), requests.Timeout('timeout')]:
            with self.subTest(error=error), self.assertRaises(requests.RequestException):
                self.discover([self.response([('111', 'Artikel am Lager')]), error])

    def test_missing_following_page_is_terminal_but_missing_first_page_fails(self):
        for status in [404, 410]:
            with self.subTest(status=status):
                links, count = self.discover([
                    self.response([('111', 'Artikel am Lager')]), self.response(status=status)])
                self.assertEqual((len(links), count), (1, 2))
                with self.assertRaises(requests.HTTPError):
                    self.discover([self.response(status=status)])

class JpcTransientRequestTests(unittest.TestCase):
    def fetch(self, outcomes, post=False):
        session = Mock()
        method = session.post if post else session.get
        method.side_effect = outcomes
        route = native.RouteSpec('test', 'https://www.jpc.de/s/test',
                                 post_params=(('filter', 'stock'),) if post else ())
        result = native.request_listing_page(session=session, route=route, url=route.url,
                                             page_number=43, timeout_seconds=25)
        return result, method

    def response(self, status, retry_after=None):
        response = Mock(status_code=status, headers={})
        if retry_after is not None:
            response.headers['Retry-After'] = retry_after
        return response

    @patch.object(native.time, 'sleep')
    def test_503_then_timeout_then_success_retries_identical_page(self, sleep):
        ok = self.response(200)
        result, method = self.fetch([self.response(503), requests.Timeout(), ok])
        self.assertIs(result, ok)
        self.assertEqual(method.call_count, 3)
        self.assertTrue(all(call == method.call_args_list[0] for call in method.call_args_list))
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [60, 120])

    @patch.object(native.time, 'sleep')
    def test_persistent_503_returns_failure_after_three_requests(self, sleep):
        result, method = self.fetch([self.response(503) for _ in range(3)])
        self.assertEqual(result.status_code, 503)
        self.assertEqual(method.call_count, 3)

    @patch.object(native.time, 'sleep')
    def test_persistent_connection_error_is_raised(self, sleep):
        with self.assertRaises(requests.ConnectionError):
            self.fetch([requests.ConnectionError() for _ in range(3)])
        self.assertEqual(sleep.call_count, 2)

    @patch.object(native.time, 'sleep')
    def test_access_denials_are_never_retried(self, sleep):
        for status in [401, 403, 429, 404, 410]:
            result, method = self.fetch([self.response(status)])
            self.assertEqual(result.status_code, status)
            self.assertEqual(method.call_count, 1)
        sleep.assert_not_called()

    @patch.object(native.time, 'sleep')
    def test_retry_after_is_honoured_and_long_wait_aborts(self, sleep):
        result, method = self.fetch([self.response(503, '60'), self.response(200)], post=True)
        self.assertEqual(result.status_code, 200)
        sleep.assert_called_once_with(60)
        self.assertEqual(method.call_args_list[0], method.call_args_list[1])
        sleep.reset_mock()
        result, method = self.fetch([self.response(503, '3600')])
        self.assertEqual((result.status_code, method.call_count), (503, 1))
        sleep.assert_not_called()

class JpcSharedIndexTests(unittest.TestCase):
    @patch.object(source.subprocess, 'Popen')
    @patch.object(source, 'route_specs', side_effect=requests.HTTPError('503'))
    def test_unavailable_shared_index_stops_before_any_child_or_write(self, routes, spawn):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {'CUREDPLANT_PRICE_EVIDENCE': str(Path(directory)/'records.jsonl')}):
            self.assertEqual(source.run(2), 1)
            spawn.assert_not_called()
            evidence = json.loads((Path(directory)/'records.jsonl').read_text())
            self.assertEqual(evidence['kind'], 'source_error')

    def test_index_http_error_and_empty_index_cannot_reduce_category_coverage(self):
        session = Mock()
        for status in [403, 503]:
            response = requests.Response()
            response.status_code = status
            response._content = b'unavailable'
            with self.subTest(status=status), \
                 patch.object(native, 'request_listing_page', return_value=response), \
                 self.assertRaises(requests.HTTPError):
                native.discover_route_index(session=session, timeout_seconds=25)
        response.status_code = 200
        with patch.object(native, 'request_listing_page', return_value=response), \
             self.assertRaises(ValueError):
            native.discover_route_index(session=session, timeout_seconds=25)

    def test_both_processes_receive_identical_complete_route_snapshot(self):
        routes = [native.RouteSpec('folk-americana', 'https://www.jpc.de/s/1238692_66705?searchtype=cid')]
        with patch.object(native, 'build_session'), \
             patch.object(native, 'discover_route_index', return_value=routes) as fetch:
            specs = source.route_specs()
        fetch.assert_called_once()
        self.assertIn('folk-americana=', specs)
        for index in range(source.SHARDS):
            command = source.command_for(index, 2, specs)
            self.assertEqual(command[command.index('--routes')+1], specs)
            self.assertNotIn('--include-route-index', command)
