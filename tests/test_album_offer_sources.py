from datetime import datetime,timezone
import json
import unittest
from unittest.mock import Mock,MagicMock,patch
from scripts.workers import album_offer_sources as src

class AlbumSource(unittest.TestCase):
 def row(self):return {'product_url':'https://shop.test/products/artist-album','shop_domain':'shop.test','source_product_id':'123','source_input':{'format':'LP'}}
 def html(self,**change):
  product={'@context':'https://schema.org','@type':'Product','url':self.row()['product_url'],'name':'Artist Album LP',
   'offers':{'@type':'Offer','url':self.row()['product_url'],'price':'25.00','priceCurrency':'EUR','availability':'https://schema.org/InStock'}}
  product.update(change)
  return '<h1>Artist Album LP</h1><script type="application/ld+json">'+json.dumps(product)+'</script>'
 def transport(self,**change):
  v={'id':123,'price':2500,'available':True,'barcode':''};v.update(change)
  return Mock(get=Mock(side_effect=[self.html(),json.dumps({'title':'Artist Album LP','variants':[v]})]),requests=[])
 def test_own_catalogue_and_html_prove_price_and_barcode_absence(self):
  result=src.verify_source(self.row(),self.transport())
  self.assertEqual((result['route'],result['price'],result['ean_status']),('ARTIST_TITLE','25.00','EAN_NOT_FOUND'))
  self.assertEqual(result['label'],'Artist Album LP')
 def test_own_catalogue_carrier_proves_vinyl_when_html_category_is_missing(self):
  row=self.row();row['source_input']={}
  body=self.html(name='Artist Album').replace('<h1>Artist Album LP</h1>','<h1>Artist Album</h1>')
  data={'title':'Artist Album','type':'LP','variants':[{'id':123,'price':2500,'available':True,'barcode':''}]}
  result=src.verify_source(row,Mock(get=Mock(side_effect=[body,json.dumps(data)]),requests=[]))
  self.assertEqual(result['format_status'],'vinyl')
  for update,reason in [({'type':'CD'},'vinyl_format_unproven'),({'title':'Another Album'},'catalogue_html_title_mismatch')]:
   with self.assertRaisesRegex(ValueError,reason):src.verify_source(row,Mock(get=Mock(side_effect=[body,json.dumps({**data,**update})]),requests=[]))
 def test_localized_collection_product_uses_its_own_catalogue_endpoint(self):
  row=self.row();row['product_url']='https://shop.test/en/collections/vinyl/products/artist-album'
  body=self.html().replace(self.row()['product_url'],row['product_url'])
  data={'title':'Artist Album LP','variants':[{'id':123,'price':2500,'available':True,'barcode':''}]}
  transport=Mock(get=Mock(side_effect=[body,json.dumps(data)]),requests=[])
  self.assertEqual(src.verify_source(row,transport)['price_basis'],'public_catalogue_json_crosschecked_own_html')
  self.assertEqual(transport.get.call_args.args[0],row['product_url']+'.js')
 def test_north_end_own_scope_ignores_shipping_and_reuses_existing_parser(self):
  row={'product_url':'https://www.northendhaarlem.nl/a-123/album/','shop_domain':'northendhaarlem.nl','source_product_id':'123','source_input':{'title_raw':'Artist Album LP','price':'25.00'}}
  body='<link rel="canonical" href="https://www.northendhaarlem.nl/a-123/album/"><div class="article product-page"><h1>Artist Album LP</h1><div class="price-container"><span class="pricetag">€ 25,00</span></div><p>Op voorraad</p><table class="article-specs"></table><p>Verzending €4,95</p></div>'
  result=src.verify_source(row,Mock(get=Mock(return_value=body),requests=[]))
  self.assertEqual((result['route'],result['price'],result['price_basis']),('ARTIST_TITLE','25.00','verified_visible_article_price_fallback'))
  import tempfile,hashlib
  from pathlib import Path
  capture={'raw':{'id':'raw','source_url':row['product_url'],'source_product_id':'123','title_raw':'Artist Album LP','target_shop_id':'shop','domain':'northendhaarlem.nl'},'source_input':row['source_input'],'product_url':row['product_url'],'observed_at':datetime.now(timezone.utc).isoformat(),
           'responses':[{'url':row['product_url'],'body':body,'sha256':hashlib.sha256(body.encode()).hexdigest()}]}
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'capture.json';path.write_text(json.dumps(capture));verified=src.verify_capture(path)
   self.assertEqual(verified['records'][0]['record']['observed_at'],capture['observed_at'])
   capture['responses'][0]['body']+='modified';path.write_text(json.dumps(capture))
   with self.assertRaisesRegex(ValueError,'capture_hash_mismatch'):src.verify_capture(path)
   capture['observed_at']='2020-01-01T00:00:00+00:00';path.write_text(json.dumps(capture))
   with self.assertRaisesRegex(ValueError,'stale_capture'):src.verify_capture(path)
 def test_found_ean_routes_out_and_invalid_code_is_never_absence(self):
  result=src.verify_source(self.row(),self.transport(barcode='0602517341289'))
  self.assertEqual((result['route'],result['gtin14']),('EAN','00602517341289'))
  with self.assertRaises(ValueError):src.verify_source(self.row(),self.transport(barcode='0602517341288'))
 def test_conflicting_code_wrong_price_or_unknown_unit_rejected(self):
  with self.assertRaises(ValueError):src.verify_source(self.row(),self.transport(price=2501))
  with self.assertRaises(ValueError):src.verify_source(self.row(),self.transport(price='25.00'))
  t=self.transport(barcode='0602517341289');t.get.side_effect=[self.html(gtin13='842812109140'),json.dumps({'title':'Artist Album LP','variants':[{'id':123,'price':2500,'available':True,'barcode':'0602517341289'}]})]
  with self.assertRaises(ValueError):src.verify_source(self.row(),t)
 def test_multiple_variants_and_unrelated_structured_product_rejected(self):
  t=Mock(get=Mock(side_effect=[self.html(),json.dumps({'title':'Artist Album LP','variants':[{'id':1},{'id':2}]})]),requests=[])
  with self.assertRaises(ValueError):src.verify_source(self.row(),t)
  t=Mock(get=Mock(return_value=self.html(url='https://shop.test/products/related')),requests=[])
  with self.assertRaises(ValueError):src.verify_source(self.row(),t)
 def test_used_signal_and_foreign_private_or_credentialed_destinations_rejected(self):
  t=Mock(get=Mock(return_value=self.html(description='Used vinyl / sleeve condition VG')),requests=[])
  with self.assertRaises(ValueError):src.verify_source(self.row(),t)
  for url,domain in [('http://shop.test/p','shop.test'),('https://other.test/p','shop.test'),('https://user:pass@shop.test/p','shop.test'),('https://127.0.0.1/p','127.0.0.1'),('https://shop.local/p','shop.local')]:
   with self.assertRaises(ValueError):src.approved_url(url,domain)
 def test_native_own_specification_barcode_is_detected_and_related_barcode_ignored(self):
  row=self.row();row['product_url']='https://shop.test/record/artist-album'
  row['source_input'].update(price='25.00',currency='EUR',price_source='listing',listing_observed_at=datetime.now(timezone.utc).isoformat())
  body='<main>'+self.html().replace(self.row()['product_url'],row['product_url'])+'<table><tr><th>Barcode</th><td>0602517341289</td></tr></table></main>'
  result=src.verify_source(row,Mock(get=Mock(return_value=body),requests=[]))
  self.assertEqual(result['route'],'EAN')
  related=body.replace('<table>','<div class="related-products"><table>').replace('</table>','</table></div>')
  result=src.verify_source(row,Mock(get=Mock(return_value=related),requests=[]))
  self.assertEqual(result['route'],'ARTIST_TITLE')
 def test_sku_is_not_assumed_to_be_a_barcode(self):
  result=src.verify_source(self.row(),self.transport(sku='0602517341289'))
  self.assertEqual(result['route'],'ARTIST_TITLE')
 def test_nested_price_specification_and_visible_price_do_not_pick_shipping(self):
  row=self.row();row['product_url']='https://shop.test/record/artist-album'
  offers={'priceSpecification':[{'@type':'UnitPriceSpecification','price':'25.00','priceCurrency':'EUR'}],'availability':'https://schema.org/InStock'}
  body='<main>'+self.html(offers=offers).replace(self.row()['product_url'],row['product_url'])+'<div class="summary"><p class="price"><span class="woocommerce-Price-amount">€25,00</span></p></div><footer>Shipping €4,95</footer></main>'
  result=src.verify_source(row,Mock(get=Mock(return_value=body),requests=[]))
  self.assertEqual((result['price'],result['price_basis']),('25.00','verified_visible_article_price_fallback'))
  with self.assertRaises(ValueError):src.verify_source(row,Mock(get=Mock(return_value=body.replace('€25,00','€26,00')),requests=[]))
 def test_physical_colour_suffix_in_heading_and_explicit_vinyl_property(self):
  product_name='Artist Album LP (Clear Vinyl)'
  t=self.transport();t.get.side_effect=[self.html(name=product_name),json.dumps({'title':product_name,'variants':[{'id':123,'price':2500,'available':True,'barcode':''}]})]
  self.assertEqual(src.verify_source(self.row(),t)['route'],'ARTIST_TITLE')
 def test_description_and_own_specification_conflicting_codes_require_review(self):
  body='<main>'+self.html(description='EAN: 0602517341289')+'<table><tr><th>EANCode</th><td>842812109140</td></tr></table></main>'
  with self.assertRaisesRegex(ValueError,'conflicting_source_barcodes'):src.verify_source(self.row(),Mock(get=Mock(return_value=body),requests=[]))
 def test_missing_product_does_not_pause_other_products_but_403_does(self):
  rows=[{**self.row(),'id':str(i),'source_record':{},'match_result':{},'offer_id':None} for i in (1,2)]
  result={'status':'validated','route':'ARTIST_TITLE','label':'Artist Album LP'}
  for error,expected,calls in [('HTTP_404',{'source_review':1,'pending_match':1},2),('HTTP_403',{'source_retry':2},1)]:
   conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=('token',)
   with patch.object(src,'claim',return_value=(rows,'token')),patch.object(src,'Transport'),patch.object(src,'verify_source',side_effect=[RuntimeError(error),result]) as verify:
    self.assertEqual(src.collect(conn,2)['statuses'],expected);self.assertEqual(verify.call_count,calls)
 def test_source_prices_refresh_and_changed_identity_clears_previous_manual_decision(self):
  row={**self.row(),'id':'queue','source_record':{'label':'Different Artist Different Album'},'match_result':{'status':'matched'},'offer_id':'offer'}
  conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=('token',);transport=self.transport()
  with patch.object(src,'claim',return_value=([row],'token')),patch.object(src,'Transport',return_value=transport):
   src.collect(conn,1)
  sql,args=conn.cursor.return_value.__enter__.return_value.execute.call_args.args
  self.assertIn('manual_group=case',sql)
  self.assertFalse(args[4]);self.assertFalse(args[5]);self.assertFalse(args[6])

if __name__=='__main__':unittest.main()
