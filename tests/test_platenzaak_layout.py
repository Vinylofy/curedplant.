import copy
import unittest
from unittest.mock import Mock

from bs4 import BeautifulSoup

from scripts.scrapers.legacy.platenzaak_legacy import parse_listing_page, extract_detail_table
from scripts.workers.ean_sources import EanSource
from scripts.workers.ean_progress import initial_state
from scripts.workers.run_daily_ean import execute

CARD = '''<article class="platenzaak-product-card">
<p class="platenzaak-product-card__artist"><a href="/collections/artist">Artist</a></p>
<h2 class="platenzaak-product-card-title"><a class="platenzaak-product-card-title__link" href="/collections/vinyl/products/album">Album</a></h2>
<div class="platenzaak-product-card-price"><span class="platenzaak-product-card-price__current">€ 34,99</span><s>€ 49,99</s></div>
<button>In winkelwagen</button></article>'''

class PlatenzaakLayoutTests(unittest.TestCase):
    def test_current_card_price_and_identity(self):
        rows = parse_listing_page(BeautifulSoup(CARD, 'html.parser'), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['artist'], rows[0]['title'], rows[0]['price'], rows[0]['availability']),
                         ('Artist', 'Album', '34.99', 'In winkelmandje'))
        self.assertTrue(rows[0]['product_url'].endswith('/collections/vinyl/products/album'))

    def test_missing_price_does_not_use_rating_or_old_price(self):
        card = CARD.replace('€ 34,99', 'onbekend')
        self.assertEqual(parse_listing_page(BeautifulSoup(card, 'html.parser'), 1)[0]['price'], '')

    def test_explicit_selected_variant_ean(self):
        soup = BeautifulSoup('<table><tr data-platenzaak-variant-ean-row><th>EAN</th><td data-platenzaak-variant-ean>0602478225260</td></tr></table>', 'html.parser')
        self.assertEqual(extract_detail_table(soup)['ean'], '0602478225260')

    def test_unrecognized_first_page_is_error_not_end_of_catalogue(self):
        source = EanSource('platenzaak', sleeper=lambda _: None)
        self.addCleanup(source.close)
        source.get = Mock(return_value=Mock(text='<html>New layout</html>'))
        with self.assertRaisesRegex(ValueError, 'refusing to mark catalogue exhausted'):
            source.catalog({'page': 1, 'seed': 0})

    def test_wrongly_exhausted_cursor_is_reset_once_without_clearing_budget(self):
        state = initial_state('platenzaak')
        state['cursor'] = {'page': 1, 'seed': 0, 'exhausted': True, 'exhausted_on': '2026-11-03'}
        state['budget'] = {'date': '2026-11-04', 'reserved': 90}
        class Progress:
            def load(self): return copy.deepcopy(state)
            def save(self, value): state.update(copy.deepcopy(value))
        class Queue:
            def candidates(self, shop, limit): return []
            def register(self, shop, rows): pass
        class Source:
            events = []
            def __init__(self, shop): pass
            def catalog(self, cursor):
                self.first = dict(cursor)
                raise ValueError('stop test')
            def close(self): pass
        result = execute('platenzaak', 10, True, progress=Progress(), queue=Queue(), source_factory=Source, today='2026-11-04')
        self.assertEqual(result['next_cursor'], {'page': 1, 'seed': 0})
        self.assertTrue(state['platenzaak_layout_v2'])
        self.assertEqual(state['budget']['reserved'], 90)

if __name__ == '__main__': unittest.main()
