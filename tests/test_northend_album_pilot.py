import unittest
from scripts.workers.northend_album_pilot import parse_source,source_identity

class NorthEndPilotSource(unittest.TestCase):
    def item(self):return {'source_product_id':'123','source_url':'https://www.northendhaarlem.nl/a-123/album/','title_raw':'Artist Album LP','listing_price':'25.00','currency':'EUR','listing_observed_at':'2026-10-31T00:00:00+00:00'}
    def body(self,code=''):
        return '<link rel="canonical" href="https://www.northendhaarlem.nl/a-123/album/"><div class="article product-page"><h1>Artist Album LP</h1><div class="price-container"><span class="pricetag">€ 25,00</span></div><p>Op voorraad</p><table class="article-specs">'+code+'</table><p>Verzending €4,95</p></div>'
    def test_own_article_price_ignores_shipping_and_missing_ean_is_not_a_failure(self):
        result=parse_source(self.body(),self.item(),'2026-10-31T01:00:00+00:00')
        self.assertEqual(result['route'],'ARTIST_TITLE');self.assertEqual(result['price'],'25.00')
        self.assertIsNone(result['source_artist'])
    def test_found_ean_routes_to_exact_worker(self):
        result=parse_source(self.body('<tr><th>EAN</th><td>842812109140</td></tr>'),self.item(),'2026-10-31T01:00:00+00:00')
        self.assertEqual(result['route'],'EAN');self.assertEqual(result['gtin14'],'00842812109140')
    def test_invalid_identifier_canonical_redirect_and_price_mismatch_are_blocked(self):
        for body in (self.body('<tr><th>EAN</th><td>842812109141</td></tr>'),self.body().replace('/a-123/','/a-999/'),self.body().replace('€ 25,00','€ 26,00')):
            with self.assertRaises(ValueError):parse_source(body,self.item(),'2026-10-31T01:00:00+00:00')
    def test_foreign_source_urls_rejected(self):
        with self.assertRaises(ValueError):source_identity('https://other.com/a-123/album/')

if __name__=='__main__':unittest.main()
