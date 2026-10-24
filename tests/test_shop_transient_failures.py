import contextlib
import io
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone

import requests

from scripts.scrapers.usf.jobs import refresh_soundsvenlo_listing_prices as sounds
from scripts.scrapers.usf.jobs import refresh_northendhaarlem_listing_prices as north
from scripts.workers.run_catalog_price import command_for


class ShopTransientFailureTests(unittest.TestCase):
    def test_sounds_retries_same_page_then_fails_closed(self):
        args = sounds.build_parser().parse_args(['--max-pages', '1'])
        with patch.object(sounds, 'fetch_listing_html', side_effect=requests.Timeout('temporary')) as fetch, \
             patch.object(sounds.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'Incomplete Sounds Venlo'):
                sounds.run_listing(args, Mock())
        self.assertEqual(fetch.call_count, args.max_page_failures)
        self.assertEqual(len({call.args[1] for call in fetch.call_args_list}), 1)

    def test_sounds_does_not_retry_site_denial(self):
        args = sounds.build_parser().parse_args(['--max-pages', '1'])
        response = requests.Response()
        response.status_code = 403
        error = requests.HTTPError(response=response)
        with patch.object(sounds, 'fetch_listing_html', side_effect=error) as fetch, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(requests.HTTPError):
                sounds.run_listing(args, Mock())
        self.assertEqual(fetch.call_count, 1)

    def test_northend_retries_server_error_without_changing_url(self):
        session = Mock()
        session.get.side_effect = [Mock(status_code=502), Mock(status_code=200, text='listing')]
        with patch.object(north.time, 'sleep'):
            self.assertEqual(north.fetch_html('https://www.northendhaarlem.nl/c-test/', session=session), (200, 'listing'))
        self.assertEqual([call.args[0] for call in session.get.call_args_list],
                         ['https://www.northendhaarlem.nl/c-test/'] * 2)

    def test_northend_does_not_retry_access_denial(self):
        for status in (403, 429):
            with self.subTest(status=status):
                session = Mock()
                session.get.return_value = Mock(status_code=status, text='denied')
                self.assertEqual(north.fetch_html('https://www.northendhaarlem.nl/', session=session), (status, 'denied'))
                session.get.assert_called_once()

    def test_northend_pilot_is_one_category_full_run_keeps_all_categories(self):
        self.assertIn('--category-limit', command_for('northendhaarlem', 2))
        self.assertNotIn('--category-limit', command_for('northendhaarlem', 0))


if __name__ == '__main__':
    unittest.main()
