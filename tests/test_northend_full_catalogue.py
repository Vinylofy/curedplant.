import copy
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,MagicMock,patch
import requests
from scripts.workers import northend_full_catalogue as full
from scripts.workers.northend_album_pilot import parse_source
from tests import test_northend_album_pilot as pilot_tests

class FullCatalogue(unittest.TestCase):
    def source(self,ident='123'):
        return {'source_url':f'https://www.northendhaarlem.nl/a-{ident}/a/','shop_domain':'northendhaarlem.nl','currency':'EUR',
          'availability':'in_stock','raw':{'source_product_id':ident,'category_id':'1234','category_slug':'pop','category_name':'Pop',
          'page':1,'title_raw':'Artist Album LP'}}
    def state(self):return full.initialize([self.source('123'),self.source('456')],'41190630661','chain')
    def result(self):
        fixture=pilot_tests.NorthEndPilotSource()
        return parse_source(fixture.body('<tr><th>EAN</th><td>0602517341289</td></tr>'),fixture.item(),full.now())
    def test_seed_deduplicates_id_and_rejects_foreign_catalogue(self):
        self.assertEqual(len(full.seed_records([self.source(),self.source()])),1)
        bad=self.source();bad['source_url']='https://other.com/a-123/'
        with self.assertRaises(ValueError):full.seed_records([bad])
        bad=self.source();bad['raw']['category_slug']='../../other'
        with self.assertRaises(ValueError):full.seed_records([bad])
    def test_checkpoint_detects_changed_seed_and_skipped_cursor(self):
        state=self.state();full.validate_checkpoint(state)
        state['cursor']=1
        with self.assertRaises(ValueError):full.validate_checkpoint(state)
        state=self.state();state['records'][0]['source_product_id']='999'
        with self.assertRaises(ValueError):full.validate_checkpoint(state)
    def test_one_part_then_resume_finishes_without_repeating_products(self):
        state=self.state();transport=Mock();writer=Mock(return_value={'status':'ean_imported'})
        with tempfile.TemporaryDirectory() as folder,patch.object(full,'OUT',Path(folder)/'checkpoint.json'),patch.object(full,'verify_item',return_value=self.result()) as verify:
            full.run_batch(state,transport,batch_size=1,writer=writer)
            self.assertEqual((state['cursor'],state['status']),(1,'continue'))
            saved=json.loads(full.OUT.read_text());full.validate_checkpoint(saved)
            full.run_batch(saved,transport,batch_size=1,writer=writer)
            self.assertEqual((saved['cursor'],saved['status']),(2,'completed'))
            self.assertEqual([c.args[0]['source_product_id'] for c in verify.call_args_list],['123','456'])
            self.assertEqual(writer.call_count,2)
    def test_blocked_product_advances_but_access_or_network_failure_pauses(self):
        for error,status,cursor in [(ValueError('Wrong title'),'completed',2),(RuntimeError('HTTP_429'),'access_paused',0),
                                    (requests.Timeout('timeout'),'network_paused',0)]:
            with self.subTest(error=error),tempfile.TemporaryDirectory() as folder,patch.object(full,'OUT',Path(folder)/'checkpoint.json'),patch.object(full,'verify_item',side_effect=error):
                state=self.state();full.run_batch(state,Mock());self.assertEqual((state['status'],state['cursor']),(status,cursor))
    def test_database_failure_stops_without_consuming_next_source(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(full,'OUT',Path(folder)/'checkpoint.json'),patch.object(full,'verify_item',return_value=self.result()):
            state=self.state()
            with self.assertRaises(RuntimeError):full.run_batch(state,Mock(),writer=Mock(side_effect=RuntimeError('db fault')))
            self.assertEqual((state['status'],state['cursor']),( 'infrastructure_paused',0))
    def test_publication_uses_ean_writer_and_actual_listing_time(self):
        result=self.result();result['listing_observed_at']=full.now();conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect=[None,None]
        with patch.object(full,'ensure_shop',return_value='shop'),patch.object(full,'upsert_product',return_value=('product',False)),patch.object(full,'upsert_price',return_value=(False,True)) as price,patch.object(full,'maybe_insert_history',return_value=True):
            answer=full.persist_result(conn,result,'chain');self.assertEqual(answer['status'],'ean_imported')
            self.assertEqual(price.call_args.args[-1],datetime.fromisoformat(result['listing_observed_at']))
    def test_newer_listing_price_is_preserved_and_no_ean_stays_raw(self):
        result=self.result();result['listing_observed_at']=full.now();conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect=[None,(datetime.now(timezone.utc)+timedelta(minutes=1),)]
        with patch.object(full,'ensure_shop',return_value='shop'),patch.object(full,'upsert_product',return_value=('product',False)),patch.object(full,'upsert_price') as price:
            self.assertEqual(full.persist_result(conn,result,'chain')['status'],'ean_kept_newer_listing_price');price.assert_not_called()
        conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=None
        result.update(route='ARTIST_TITLE',gtin14=None)
        with patch.object(full,'upsert_product') as product:
            self.assertEqual(full.persist_result(conn,result,'chain')['status'],'raw_album_review_only');product.assert_not_called()
    def test_invalid_and_old_source_cannot_write_and_committed_source_is_idempotent(self):
        result=self.result();result['listing_observed_at']=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat();conn=MagicMock()
        with self.assertRaises(ValueError):full.persist_result(conn,result,'chain')
        conn.transaction.assert_not_called()
        result['listing_observed_at']=full.now();result['status']='blocked'
        with self.assertRaises(ValueError):full.persist_result(conn,result,'chain')
        result['status']='validated';conn.cursor.return_value.__enter__.return_value.fetchone.return_value=('existing',)
        with patch.object(full,'upsert_product') as product:
            self.assertEqual(full.persist_result(conn,result,'chain')['status'],'already_written');product.assert_not_called()
    def test_full_detail_can_collect_preorder_ean_without_weakening_pilot(self):
        fixture=pilot_tests.NorthEndPilotSource();body=fixture.body('<tr><th>EAN</th><td>0602517341289</td></tr>').replace('Op voorraad','Op bestelling')
        item={**fixture.item(),'listing_availability':'preorder'}
        with self.assertRaises(ValueError):parse_source(body,item,full.now())
        result=parse_source(body,item,full.now(),require_in_stock=False)
        self.assertEqual((result['route'],result['availability']),('EAN','preorder'))
    def test_actual_listing_parser_provides_fresh_detail_price_and_ean(self):
        fixture=pilot_tests.NorthEndPilotSource();item=full.seed_records([self.source()])[0]
        listing='<ul><li><a href="/a-123/album/">Artist Album LP</a><p>Op voorraad € 25,00 Bestel dit nieuwe vinylalbum vandaag bij North End Haarlem</p></li></ul>'
        transport=Mock();transport.get.side_effect=[listing,fixture.body('<tr><th>EAN</th><td>0602517341289</td></tr>')]
        result=full.verify_item(item,transport,{})
        self.assertEqual((result['route'],result['gtin14'],result['price']),('EAN','00602517341289','25.00'))
        self.assertEqual(result['listing_source_url'],'https://www.northendhaarlem.nl/c-1234/pop/')
        self.assertLess((datetime.now(timezone.utc)-datetime.fromisoformat(result['listing_observed_at'])).total_seconds(),10)

if __name__=='__main__':unittest.main()
