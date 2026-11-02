import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import requests
from scripts.scrapers import velvetdelft as shop
from scripts.importers.import_velvetdelft import map_velvet_row,SHOP_DEFINITION
from scripts.importers.registry import get_shop_importer
from scripts.importers.runner import validate_source_file
from scripts.scrapers.usf.jobs.velvetdelft_pipeline import preview,isolated_only,load_rows

FIX=Path(__file__).parent/'fixtures/velvetdelft'

def fixture(name):return (FIX/(name+'.html')).read_text()
def good():
    row=shop.parse_listing(fixture('home'),shop.BASE+'/nl')['records'][0]
    return shop.enrich(row,fixture('detail'))

class SourceTests(unittest.TestCase):
    def test_genres_and_barcode_verified_on_actual_detail(self):
        self.assertEqual(len(shop.GENRES),13)
        r=good();self.assertEqual(r['gtin14'],'08720589667907');self.assertEqual(r['price'],'19.99');self.assertEqual(r['ean_status'],'verified')
    def test_ajax_filters_and_page_two_are_actual_different_releases(self):
        cfg=shop.block_config(fixture('controls-prog'))
        self.assertEqual(cfg['payload']['media'],'5,6,7,11')
        self.assertEqual(cfg['payload']['instockonly'],'false')
        first=shop.parse_listing(fixture('filtered-prog-1'),shop.BASE+'/nl/pagina/prog')
        second=shop.parse_listing(fixture('filtered-prog-2'),shop.BASE+'/nl/pagina/prog?page=2')
        self.assertEqual(first['pagination']['total'],271)
        self.assertEqual(second['pagination']['page'],2)
        self.assertFalse({r['source_product_id'] for r in first['records']} & {r['source_product_id'] for r in second['records']})
        self.assertEqual(len(first['excluded']),0)
        self.assertIn('/products/blockitems?page=2',first['next_url'])
    def test_mixed_listing_prices_and_format_exclusions(self):
        data=shop.parse_listing(fixture('prog'),shop.BASE+'/nl/pagina/prog')
        self.assertEqual(len(data['records'])+len(data['excluded']),100)
        self.assertTrue(data['excluded']);self.assertTrue(all(shop.VINYL.fullmatch(r['format']) for r in data['records']))
        self.assertIn('page=2',data['next_url'])
    def test_jazz_uses_observed_genre_route(self):
        self.assertIn('/nl/genre/jazz?page=2',shop.parse_listing(fixture('jazz'),shop.BASE+'/nl/pagina/jazz')['next_url'])
    def test_promo_card_not_counted_in_primary_pagination(self):
        r=shop.parse_listing(fixture('kpop'),shop.BASE+'/nl/pagina/kpop')
        self.assertEqual(r['pagination']['shown'],48);self.assertEqual(len(r['excluded']),48)
    def test_bad_publisher_totals_never_prove_complete(self):
        r=shop.parse_listing(fixture('speciale-uitgaven'),shop.BASE+'/nl/pagina/speciale-uitgaven')
        self.assertTrue(r['pagination']['bounded_collection']);self.assertIn('count_warning',r['pagination'])
    def test_sale_price_not_struck_regular_or_shipping(self):
        from bs4 import BeautifulSoup
        card=BeautifulSoup('<div><div onclick="add_to_cart(1)"><del>€ 39,99</del> € 24,99</div>Shipping € 6,95</div>','html.parser')
        self.assertEqual(shop.price(card),('24.99','39.99'))
        card=BeautifulSoup('<div onclick="add_to_cart(1)">€ 24,99 € 6,95</div>','html.parser')
        self.assertEqual(shop.price(card),(None,None))
    def test_formats_used_bundles(self):
        for f in ['1- LP','2-LP','1-7-inch','1-10-inch','1- 12-inch maxi-single']:
            self.assertTrue(shop.VINYL.fullmatch(f),f)
        for f in ['CD','LP+CD','Merchandise','Blu Ray','SACD','DVD','1-Merchandise']:
            self.assertFalse(shop.VINYL.fullmatch(f),f)
    def test_stock_categories_never_guess_stock(self):
        for t,a in [('op voorraad','in_stock'),('verwacht: 4 dagen','supplier_order'),('pre-order','preorder'),('niet beschikbaar','out_of_stock'),('Winkel','unknown'),('','unknown')]:
            self.assertEqual(shop.availability(t),a)
    def test_detail_price_and_availability_never_overwrite_listing(self):
        row=shop.parse_listing(fixture('home'),shop.BASE+'/nl')['records'][0]
        detail=fixture('detail')+'<div>€ 0,01 Uitverkocht</div>'
        out=shop.enrich(row,detail)
        self.assertEqual(out['price'],row['price']);self.assertEqual(out['availability'],row['availability']);self.assertEqual(out['listing_observed_at'],row['listing_observed_at'])
    def test_barcode_conflicts_invalid_and_missing(self):
        row=good()
        with self.assertRaisesRegex(ValueError,'checksum'):shop.enrich(row,fixture('detail').replace('8720589667907</strong>','8720589667908</strong>'))
        r=copy.deepcopy(row);r['url_barcodes']=['0602455508508']
        with self.assertRaisesRegex(ValueError,'Conflicting'):shop.enrich(r,fixture('detail'))
        no=fixture('detail').replace('<small>barcode</small>','<small>not_barcode</small>')
        # Use BeautifulSoup to avoid relying on whitespace around the source label.
        from bs4 import BeautifulSoup
        s=BeautifulSoup(fixture('detail'),'html.parser');s.select_one('small').string='sku'
        self.assertEqual(shop.enrich(row,str(s))['ean_status'],'missing')
    def test_jsonld_product_barcode_conflicts_are_not_ignored(self):
        html=fixture('detail')+'<script type="application/ld+json">{"@type":"Product","sku":"544832","gtin13":"0602455508508"}</script>'
        with self.assertRaisesRegex(ValueError,'Conflicting'):shop.enrich(good(),html)
    def test_wrong_release_and_foreign_urls_fail(self):
        with self.assertRaisesRegex(ValueError,'release conflict'):shop.enrich(good(),fixture('detail').replace('/544832/','/544833/'))
        for u in ['http://www.velvetdelft.nl/nl','https://evil.test/nl/release/1/a','https://x@www.velvetdelft.nl/nl']:
            with self.assertRaises(ValueError):shop.safe_url(u)
    def test_robots_and_no_retry_access_blocks(self):
        client=shop.Transport.__new__(shop.Transport);client.delay=3;client.last=0;client.requests=[]
        from urllib.robotparser import RobotFileParser
        client.robots=RobotFileParser();client.robot_rules=(FIX/'robots.txt').read_text().splitlines();client.robots.parse(client.robot_rules);client.session=Mock()
        with self.assertRaisesRegex(RuntimeError,'robots'):client.get(shop.BASE+'/nl/products/search/')
        client.session.get.assert_not_called()
        for code in [403,429]:
            client.session.reset_mock();client.session.get.return_value=Mock(status_code=code,content=b'blocked')
            with patch('scripts.scrapers.velvetdelft.time.sleep'):
                with self.assertRaisesRegex(RuntimeError,'HTTP '+str(code)):client.get(shop.BASE+'/nl/pagina/prog')
            self.assertEqual(client.session.get.call_count,1)
    def test_ignored_page_and_empty_fail(self):
        with self.assertRaisesRegex(ValueError,'ignored'):shop.parse_listing(fixture('prog'),shop.BASE+'/nl/pagina/prog?page=2')
        with self.assertRaisesRegex(ValueError,'empty'):shop.parse_listing('<html/>',shop.BASE+'/nl/pagina/prog')
    def test_manual_registry_disabled_and_strict_importer(self):
        self.assertIs(get_shop_importer('velvetdelft'),SHOP_DEFINITION)
        self.assertFalse(SHOP_DEFINITION.include_in_all)
        r=good();rec,err=map_velvet_row(r,1);self.assertIsNone(err);self.assertEqual(rec.price,19.99)
        for key,value in [('ean','8720589667908'),('gtin14','00000000000000'),('price','NaN'),('condition','used'),('currency','USD'),('ean_status','pending'),('listing_observed_at','2000-01-01T00:00:00+00:00')]:
            bad={**r,key:value};self.assertIsNone(map_velvet_row(bad,1)[0],key)
        self.assertEqual(map_velvet_row({**r,'availability':'supplier_order'},1)[0].availability,'unknown')
    def test_pipeline_preview_does_not_open_database(self):
        with patch('psycopg.connect',side_effect=AssertionError('DB must not open')):
            r=good();report=preview([r,{**r,'source_product_id':'544833','ean':'','ean_status':'missing'}])
        self.assertEqual(report['promotion_valid'],1);self.assertEqual(report['quarantine'],1);self.assertFalse(report['database_writes'])
    def test_conflicting_same_gtin_editions_quarantine_instead_of_merge(self):
        r=good();other={**r,'source_product_id':'544833','source_url':r['source_url'].replace('/544832/','/544833/'),'format':'2-LP','price':'29.99'}
        result=preview([r,other])
        self.assertEqual(result['promotion_valid'],0)
        self.assertTrue(all(x['reason']=='conflicting_gtin_offers' for x in result['records']))
    def test_test_database_guard(self):
        with self.assertRaises(ValueError):isolated_only('postgresql://user@prod.example/postgres')
        isolated_only('postgresql://user@127.0.0.1/postgres')
    def test_resume_skips_verified_details(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json';r=good();shop.save(p,{'version':1,'shop_id':'velvetdelft','records':{r['source_product_id']:r},'categories':{},'requests':[]})
            client=Mock(requests=[])
            shop.collect('details',p,transport=client)
            client.get.assert_not_called()
            self.assertTrue(validate_source_file(SHOP_DEFINITION,p.parent/'products.csv').ok)
    def test_block_preserves_checkpoint_and_error(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json';r=good();r['detail_next_at']='';shop.save(p,{'version':1,'shop_id':'velvetdelft','records':{r['source_product_id']:r},'categories':{},'requests':[]})
            client=Mock(requests=[]);client.get.side_effect=RuntimeError('HTTP 429; stopped')
            with self.assertRaises(RuntimeError):shop.collect('details',p,transport=client)
            self.assertEqual(len(json.loads(p.read_text())['records']),1);self.assertIn('429',json.loads(p.read_text())['error'])

if __name__=='__main__':unittest.main()
