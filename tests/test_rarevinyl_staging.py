import unittest
from scripts.workers.rarevinyl_staging import preview_record

def record(**updates):
    row = {'url':'https://eu.rarevinyl.com/products/example', 'source_id':'123',
           'title_raw':'Artist Album LP', 'artist':'Artist', 'album_raw':'Album',
           'format_status':'vinyl', 'condition_status':'new', 'barcode':'0602508046131',
           'price':'29.95', 'availability':'in_stock',
           'condition_evidence':'Factory sealed from new. This item is unplayed.'}
    return row | updates

class StagingTests(unittest.TestCase):
    def test_valid_ean(self):
        self.assertEqual(preview_record(record())['route'], 'ean_staging')
    def test_missing_barcode_preserves_artist_title(self):
        result = preview_record(record(barcode=None))
        self.assertEqual(result['route'], 'artist_title')
        self.assertEqual(result['raw']['payload']['artist_raw'], 'Artist')
    def test_invalid_or_unsafe(self):
        self.assertEqual(preview_record(record(barcode='0602508046132'))['route'], 'quarantine')
        self.assertEqual(preview_record(record(barcode=None,barcode_raw='0602508046132',barcode_status='invalid'))['route'], 'quarantine')
        self.assertEqual(preview_record(record(condition_status='unknown'))['route'], 'quarantine')
        with self.assertRaises(ValueError): preview_record(record(url='https://evil.example/products/example'))
        with self.assertRaises(ValueError): preview_record(record(url='https://evil@eu.rarevinyl.com/products/example'))

if __name__ == '__main__': unittest.main()
