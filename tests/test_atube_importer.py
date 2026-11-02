from datetime import datetime,timezone
from pathlib import Path
import unittest
from scripts.scrapers.atubehighfidelity import parse_listing,parse_detail
from scripts.importers.import_atubehighfidelity import map_atube_row,SHOP_DEFINITION
from scripts.importers.registry import get_shop_importer

class Importer(unittest.TestCase):
 def row(self):
  root=Path(__file__).parent/'fixtures/atubehighfidelity';at=datetime.now(timezone.utc).isoformat()
  listing=next(r for r in parse_listing((root/'listing.html').read_text(),at) if r['source_product_id']=='64226')
  return parse_detail((root/'detail-doe-maar.html').read_text(),listing,at)
 def test_real_ean_detail_maps_with_listing_timestamp_and_price(self):
  row=self.row();record,reason=map_atube_row(row,1)
  self.assertIsNone(reason);self.assertEqual(record.ean,'0602455508508');self.assertEqual(record.price,34.5)
  self.assertEqual(record.captured_at.isoformat(),row['listing_observed_at']);self.assertEqual(get_shop_importer('atubehighfidelity'),SHOP_DEFINITION)
 def test_non_ean_and_unverified_rows_never_enter_exact_import(self):
  for fields in [dict(route='ARTIST_TITLE',ean_raw=None),dict(ean_raw='0602455508509'),dict(price='150'),dict(condition_status='used'),dict(status='pending')]:
   row={**self.row(),**fields};self.assertIsNone(map_atube_row(row,1)[0])

if __name__=='__main__':unittest.main()
