import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from scripts.workers.run_ean_detail import command_for, preflight_command
from scripts.scrapers.usf.jobs import detail_shop3345, detail_soundsvenlo
from scripts.scrapers.usf.jobs.refresh_myrecordstore_listing_prices import extract_listing_card_prices


class RedRepairsTests(unittest.TestCase):
    def test_price_badge_stays_in_own_product_card(self):
        soup = BeautifulSoup('''<main><p>Verzending 4,99</p>
            <div><a href="/item/one">Album 1</a><p class="bg-(--secondary)">26,99</p></div>
            <div><a href="/item/two">Album 2</a><p class="bg-(--secondary)">31,99</p></div></main>''', 'html.parser')
        self.assertEqual(extract_listing_card_prices(soup.select_one('a')), ['26.99'])

    def test_dry_runs_fetch_live_sources_and_write_routes_use_native_cli(self):
        self.assertIn('live_detail_pilot', ' '.join(command_for('cdhal', 25)))
        self.assertIn('scripts.scrapers.usf.jobs.detail_cdhal', command_for('cdhal', 25, True))
        self.assertIn('scripts.scrapers.usf.jobs.detail_colouredvinyl', command_for('colouredvinyl', 25, True))
        self.assertIn('--skip-delist-missing', command_for('fiftiesstore', 25, True))
        self.assertIsNone(preflight_command('cdhal', 25, False))
        self.assertIn('--register-only', preflight_command('soundshaarlem', 25, True))

    def run_native(self, module, write=False):
        row = {'id': 'link-1', 'source_url': module.BASE_URL + '/product/',
               'payload': {'availability': 'in_stock', 'price': '27.99', 'title': 'Album'}}
        response = Mock(status_code=200, text='<h1>Album</h1><p>EAN 8719262044807</p>')
        response.raise_for_status.return_value = None
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(module, 'fetch_detail_queue', return_value=[row]))
            session = stack.enter_context(patch.object(module.requests, 'Session'))
            session.return_value.get.return_value = response
            insert = stack.enter_context(patch.object(module, 'insert_raw_shop_scrape', return_value='raw-1'))
            mark = stack.enter_context(patch.object(module, 'mark_detail_scraped'))
            if module is detail_shop3345:
                stack.enter_context(patch.object(module, 'mark_detail_ean_found'))
            stack.enter_context(patch('sys.argv', ['worker', '--limit', '1', '--sleep', '0'] + (['--write'] if write else [])))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.assertEqual(module.main(), 0)
            session.return_value.get.assert_called_once()
            if not write:
                insert.assert_not_called()
                mark.assert_not_called()
            return insert

    def test_venlo_dry_run_fetches_details_without_mutations(self):
        self.run_native(detail_soundsvenlo)

    def test_shop3345_dry_run_fetches_details_without_mutations(self):
        self.run_native(detail_shop3345)

    def test_shop3345_enrichment_cannot_publish_price_or_stock(self):
        insert = self.run_native(detail_shop3345, write=True)
        self.assertIsNone(insert.call_args.kwargs['price_raw'])
        self.assertIsNone(insert.call_args.kwargs['availability_raw'])


if __name__ == '__main__':
    unittest.main()
