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
  return Mock(get=Mock(side_effect=[self.html(),json.dumps({'variants':[v]})]),requests=[])
 def test_own_catalogue_and_html_prove_price_and_barcode_absence(self):
  result=src.verify_source(self.row(),self.transport())
  self.assertEqual((result['route'],result['price'],result['ean_status']),('ARTIST_TITLE','25.00','EAN_NOT_FOUND'))
  self.assertEqual(result['label'],'Artist Album LP')
 def test_found_ean_routes_out_and_invalid_code_is_never_absence(self):
  result=src.verify_source(self.row(),self.transport(barcode='0602517341289'))
  self.assertEqual((result['route'],result['gtin14']),('EAN','00602517341289'))
  with self.assertRaises(ValueError):src.verify_source(self.row(),self.transport(barcode='0602517341288'))
 def test_conflicting_code_wrong_price_or_unknown_unit_rejected(self):
  with self.assertRaises(ValueError):src.verify_source(self.row(),self.transport(price=2501))
  with self.assertRaises(ValueError):src.verify_source(self.row(),self.transport(price='25.00'))
  t=self.transport(barcode='0602517341289');t.get.side_effect=[self.html(gtin13='842812109140'),json.dumps({'variants':[{'id':123,'price':2500,'available':True,'barcode':'0602517341289'}]})]
  with self.assertRaises(ValueError):src.verify_source(self.row(),t)
 def test_multiple_variants_and_unrelated_structured_product_rejected(self):
  t=Mock(get=Mock(side_effect=[self.html(),json.dumps({'variants':[{'id':1},{'id':2}]})]),requests=[])
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
  t=self.transport();t.get.side_effect=[self.html(name=product_name),json.dumps({'variants':[{'id':123,'price':2500,'available':True,'barcode':''}]})]
  self.assertEqual(src.verify_source(self.row(),t)['route'],'ARTIST_TITLE')
 def test_description_and_own_specification_conflicting_codes_require_review(self):
  body='<main>'+self.html(description='EAN: 0602517341289')+'<table><tr><th>EANCode</th><td>842812109140</td></tr></table></main>'
  with self.assertRaisesRegex(ValueError,'conflicting_source_barcodes'):src.verify_source(self.row(),Mock(get=Mock(return_value=body),requests=[]))
 def test_source_prices_refresh_and_changed_identity_clears_previous_manual_decision(self):
  row={**self.row(),'id':'queue','source_record':{'label':'Different Artist Different Album'},'match_result':{'status':'matched'},'offer_id':'offer'}
  conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=('token',);transport=self.transport()
  with patch.object(src,'claim',return_value=([row],'token')),patch.object(src,'Transport',return_value=transport):
   src.collect(conn,1)
  sql,args=conn.cursor.return_value.__enter__.return_value.execute.call_args.args
  self.assertIn('manual_group=case',sql)
  self.assertFalse(args[4]);self.assertFalse(args[5]);self.assertFalse(args[6])

if __name__=='__main__':unittest.main()
