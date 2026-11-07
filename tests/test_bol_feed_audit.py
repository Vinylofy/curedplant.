from datetime import datetime,timedelta,timezone
from decimal import Decimal
import unittest
from unittest.mock import patch
from scripts.importers.bol_feed import FeedError
from scripts.importers.common import strict_normalize_gtin
from scripts.workers.bol_feed_audit import classify_existing,audit_catalogue

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.product={'ean':'4050538793437','gtin_normalized':strict_normalize_gtin('4050538793437'),
                      'format_label':'LP','last_seen_at':self.now,'price':Decimal('28.89'),
                      'availability':'in_stock','currency':'EUR'}
    def test_missing_valid_fresh_vinyl_is_a_real_parity_candidate(self):
        result=classify_existing(self.product,set(),self.now)
        self.assertFalse(result['present']);self.assertTrue(result['api_eligible']);self.assertTrue(result['frontend_visible'])
    def test_stale_or_preorder_offers_are_not_reported_as_visible(self):
        for change in [{'last_seen_at':self.now-timedelta(days=3)},{'availability':'preorder'},
                       {'currency':'USD'},{'price':Decimal('0')}]:
            row={**self.product,**change}
            self.assertFalse(classify_existing(row,set(),self.now)['frontend_visible'])
    def test_bad_barcode_conflicting_identity_or_cd_are_not_api_targets(self):
        for change in [{'ean':'invalid'},{'gtin_normalized':'00000000000000'},{'format_label':'CD'}]:
            result=classify_existing({**self.product,**change},set(),self.now)
            self.assertFalse(result['api_eligible']);self.assertIsNotNone(result['reason'])
    def test_present_barcode_is_recognised_without_fuzzy_title_matching(self):
        self.assertTrue(classify_existing(self.product,{self.product['gtin_normalized']},self.now)['present'])
    def test_catalogue_facts_keep_only_schema_and_format_category_evidence(self):
        import json
        from unittest.mock import Mock
        from scripts.workers.bol_feed_audit import catalogue_facts
        payload={'description':'private-description','images':['private-image'],
                 'attributes':[{'name':'Drager','value':'LP'},{'name':'Artiest','value':'private-artist'}],
                 'categories':[{'id':'1','name':'Muziek'}]}
        with patch('scripts.workers.bol_feed_audit.request_json',return_value=payload):
            facts=catalogue_facts(Mock(token='private-token'),'4050538793437')
        encoded=json.dumps(facts)
        self.assertIn('LP',encoded);self.assertNotIn('private-',encoded)

    def test_incomplete_or_failed_source_is_rejected_before_database_access(self):
        with patch('scripts.workers.bol_feed_audit.psycopg.connect') as connection:
            for plan in [{'complete_feed':False},{'complete_feed':True,'errors':['failure']}]:
                with self.assertRaises(FeedError):audit_catalogue(plan,'')
            connection.assert_not_called()
