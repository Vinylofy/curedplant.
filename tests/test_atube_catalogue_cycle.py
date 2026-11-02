import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from scripts.scrapers import atubehighfidelity as shop
from scripts.workers.atube_catalogue_cycle import collect

class Cycle(unittest.TestCase):
 def rows(self):
  rows=shop.parse_listing((Path(__file__).parent/'fixtures/atubehighfidelity/listing.html').read_text(),shop.stamp())
  return [r for r in rows if not r['review_reasons']][:3]
 def test_resume_advances_without_repeating_verified_details(self):
  t=Mock(requests=[]);rows=self.rows()
  def verified(body,row,at):return {**row,'status':'validated','detail_status':'ok','detail_observed_at':at}
  with tempfile.TemporaryDirectory() as root,patch.object(shop,'catalogue',return_value=(rows,{'complete':True,'loaded':3})),patch.object(shop,'parse_detail',side_effect=verified):
   p=Path(root)/'state.json'
   for n in range(3):
    result=collect(p,1,transport=t);self.assertEqual(len([r for r in result['records'] if r['status']=='validated']),n+1)
   self.assertTrue(result['complete']);self.assertEqual(t.get.call_count,3)
   collect(p,1,transport=t);self.assertEqual(t.get.call_count,3)
 def test_three_failures_freeze_only_bad_record(self):
  t=Mock(requests=[]);rows=self.rows()[:2]
  def parse(body,row,at):
   if row['source_url']==rows[0]['source_url']:raise ValueError('variant_unproven')
   return {**row,'status':'validated','detail_status':'ok','detail_observed_at':at}
  with tempfile.TemporaryDirectory() as root,patch.object(shop,'catalogue',return_value=(rows,{'complete':True,'loaded':2})),patch.object(shop,'parse_detail',side_effect=parse):
   p=Path(root)/'state.json'
   for _ in range(3):result=collect(p,2,transport=t)
   self.assertTrue(result['complete']);self.assertEqual(result['counts'],{'frozen':1,'validated':1});self.assertEqual(result['records'][0]['attempts'],3)
 def test_access_denial_stops_shop_and_persists_pending_work(self):
  t=Mock(requests=[]);t.get.side_effect=RuntimeError('HTTP_403')
  with tempfile.TemporaryDirectory() as root,patch.object(shop,'catalogue',return_value=(self.rows(),{'complete':True,'loaded':3})):
   p=Path(root)/'state.json';result=collect(p,3,transport=t)
   self.assertEqual(t.get.call_count,1);self.assertFalse(result['complete']);self.assertIn('HTTP_403',result['error']);self.assertEqual(json.loads(p.read_text())['waiting'],3)
 def test_listing_only_and_unproven_catalogue_end(self):
  t=Mock(requests=[])
  with tempfile.TemporaryDirectory() as root,patch.object(shop,'catalogue',return_value=(self.rows(),{'complete':True,'loaded':3})):
   result=collect(Path(root)/'s.json',transport=t,listing_only=True);t.get.assert_not_called();self.assertEqual(result['waiting'],3)
  with tempfile.TemporaryDirectory() as root,patch.object(shop,'catalogue',return_value=(self.rows(),{'complete':False,'loaded':3})):
   result=collect(Path(root)/'s.json',transport=t);self.assertFalse(result['complete']);self.assertIn('end not proven',result['error'])

if __name__=='__main__':unittest.main()
