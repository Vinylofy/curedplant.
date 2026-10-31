import unittest
from scripts.workers.album_draft_prices import candidates

class DraftPrices(unittest.TestCase):
    def row(self,**kw):return {'source_url':'https://www.northendhaarlem.nl/a-123/a/','price':'25.00','currency':'EUR','availability':'in_stock',**kw}
    def test_scope_and_money(self):
        self.assertEqual(len(candidates([self.row()])),1)
        for change in ({'price':'NaN'},{'price':'-1'},{'currency':'USD'},{'source_url':'https://other.com/a-123/a/'},{'availability':'unproven'}):
            self.assertEqual(candidates([self.row(**change)]),[])
    def test_source_article_dedup_and_conflicts(self):
        self.assertEqual(len(candidates([self.row(),self.row(source_url='https://northendhaarlem.nl/a-123/b/') ])),1)
        self.assertEqual(candidates([self.row(),self.row(price='26.00')]),[])

if __name__=='__main__':unittest.main()
