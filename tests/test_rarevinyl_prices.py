import unittest
from datetime import datetime, timedelta, timezone
from scripts.workers.rarevinyl_prices import price_records

def row(**changes):
    source = {'url':'https://eu.rarevinyl.com/products/example', 'condition_status':'new',
              'format_status':'vinyl', 'currency':'EUR', 'price':'19.95',
              'availability':'in_stock', 'observed_at':datetime.now(timezone.utc).isoformat(),
              'detail_checked_at':datetime.now(timezone.utc).isoformat(),
              'condition_evidence':'Factory sealed from new. This item is unplayed.'}
    return source | changes

class PriceTests(unittest.TestCase):
    def test_valid_listing_preserves_price_and_shop(self):
        result = price_records([row()])
        self.assertEqual(result['records'][0]['price'], '19.95')
        self.assertEqual(result['records'][0]['shop_domain'], 'eu.rarevinyl.com')
        self.assertEqual(result['database_writes'], 0)
    def test_reject_wrong_format_stale_and_foreign_url(self):
        for change in ({'condition_status':'unknown'}, {'condition_evidence':'sealed'}, {'format_status':'cd'}, {'currency':'GBP'},
                       {'price':'19.999'}, {'url':'https://evil.example/products/example'},
                       {'observed_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()}):
            self.assertEqual(len(price_records([row(**change)])['records']), 0)
    def test_conflicting_duplicate_is_error(self):
        with self.assertRaises(ValueError): price_records([row(),row(price='12.00')])

if __name__ == '__main__': unittest.main()
