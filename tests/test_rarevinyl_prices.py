import unittest
from datetime import datetime, timedelta, timezone
from scripts.workers.rarevinyl_prices import price_records, sync_existing
from unittest.mock import Mock

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
    def test_write_is_explicit_and_uses_existing_writer(self):
        writer = Mock(return_value={'updated':1, 'verified':1})
        self.assertEqual(sync_existing([row()], writer=writer)['database_writes'], 0)
        writer.assert_not_called()
        result = sync_existing([row()], writer=writer, write=True)
        self.assertEqual(result['writer']['verified'], 1)
        self.assertEqual(writer.call_args.args[0], 'rarevinyl')
        self.assertTrue(writer.call_args.kwargs['preserve_unknown'])
    def test_rejected_and_empty_batch_cannot_write(self):
        writer = Mock()
        result = sync_existing([row(condition_status='unknown')], writer=writer, write=True)
        self.assertEqual(result['database_writes'], 0)
        writer.assert_not_called()

if __name__ == '__main__': unittest.main()
