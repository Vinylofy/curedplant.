import contextlib
import unittest
from unittest.mock import Mock, patch

from scripts.scrapers.usf.core.northend_transport import NorthEndSession, canonical_url
from scripts.scrapers.usf.jobs.detail_northendhaarlem import parse_detail_page


def response(status, url='https://www.northendhaarlem.nl/test/'):
    result = Mock(status_code=status, url=url, headers={})
    return result


class NorthEndTests(unittest.TestCase):
    def test_canonical_url_accepts_only_shop(self):
        self.assertEqual(canonical_url('https://northendhaarlem.nl/a-1/'),
                         'https://www.northendhaarlem.nl/a-1/')
        with self.assertRaises(ValueError):
            canonical_url('https://another-shop.example/a-1/')

    def test_requests_reuse_session_and_keep_thirty_second_interval(self):
        clock = Mock(side_effect=[0, 5, 30])
        sleep = Mock()
        with NorthEndSession(clock=clock, sleeper=sleep) as session, \
             patch('requests.Session.get', return_value=response(200)) as fetch:
            session.get('https://northendhaarlem.nl/first/')
            session.get('https://northendhaarlem.nl/second/')
            sleep.assert_called_once_with(25.0)
            self.assertEqual(fetch.call_count, 2)

    def test_rate_limit_stops_further_requests(self):
        with NorthEndSession(sleeper=Mock()) as session, \
             patch('requests.Session.get', return_value=response(429)) as fetch:
            self.assertEqual(session.get('https://northendhaarlem.nl/first/').status_code, 429)
            self.assertEqual(session.get('https://northendhaarlem.nl/second/').status_code, 429)
            fetch.assert_called_once()

    def test_browser_context_is_kept_for_following_pages(self):
        with contextlib.ExitStack() as stack:
            # A tiny fake of the ordinary browser lifecycle, without launching
            # a browser or reaching the shop during a unit test.
            playwright = Mock()
            browser = playwright.chromium.launch.return_value
            page = browser.new_page.return_value
            page.url = 'about:blank'
            page.locator.return_value.first.count.return_value = 0
            page.goto.return_value = Mock(status=200, headers={})
            page.content.return_value = '<h1>North End</h1>'
            module = Mock()
            module.sync_playwright.return_value.start.return_value = playwright
            stack.enter_context(patch.dict('sys.modules', {'playwright.sync_api': module}))
            fetch = stack.enter_context(patch('requests.Session.get', return_value=response(403)))
            with NorthEndSession(clock=Mock(return_value=0), sleeper=Mock()) as session:
                self.assertEqual(session.get('https://northendhaarlem.nl/category/').status_code, 200)
                self.assertEqual(session.get('https://northendhaarlem.nl/product/').status_code, 200)
                self.assertEqual([c.args[0] for c in page.goto.call_args_list], [
                    'https://www.northendhaarlem.nl/',
                    'https://www.northendhaarlem.nl/category/',
                    'https://www.northendhaarlem.nl/product/'])
                fetch.assert_called_once()
                browser.new_page.assert_called_once()
            browser.close.assert_called_once()

    def test_profile_matches_working_windows_source(self):
        from scripts.workers.windows_baseline.refresh_northendhaarlem_listing_prices import REQUEST_HEADERS
        with NorthEndSession() as session:
            for key, value in REQUEST_HEADERS.items():
                self.assertEqual(session.headers[key], value)

    def test_product_navigation_clicks_existing_catalogue_link(self):
        with NorthEndSession(clock=Mock(return_value=0), sleeper=Mock()) as session:
            page = session._page = Mock(url=session.origin + '/c-1/vinyl/')
            page.locator.return_value.first.count.return_value = 1
            page.expect_navigation.return_value.__enter__ = Mock(
                return_value=Mock(value=Mock(status=200, headers={})))
            page.expect_navigation.return_value.__exit__ = Mock(return_value=False)
            page.content.return_value = '<h1>Product</h1>'
            result = session._navigate(session.origin + '/a-123/album/')
            self.assertEqual(result.status_code, 200)
            page.locator.return_value.first.click.assert_called_once()
            page.goto.assert_not_called()
            self.assertEqual(session.events[-1]['navigation'], 'link')
            session._page = None

    def test_blocked_homepage_stops_before_category_or_product(self):
        module = Mock()
        playwright = module.sync_playwright.return_value.start.return_value
        page = playwright.chromium.launch.return_value.new_page.return_value
        page.url = 'about:blank'
        page.locator.return_value.first.count.return_value = 0
        page.goto.return_value = Mock(status=403, headers={'cf-mitigated': 'challenge'})
        page.content.return_value = 'blocked'
        with patch.dict('sys.modules', {'playwright.sync_api': module}), \
             patch('requests.Session.get', return_value=response(403)), \
             NorthEndSession(clock=Mock(return_value=0), sleeper=Mock()) as session:
            self.assertEqual(session.get(session.origin + '/c-1/vinyl/').status_code, 403)
            self.assertEqual(session.get(session.origin + '/a-1/album/').status_code, 403)
            page.goto.assert_called_once()

    def test_only_current_product_barcode_is_used(self):
        html = '''<nav>Menu Meer Barcode 8719262044807</nav>
          <div class="article product-page"><h1>George Michael - Faith LP</h1>
           <p>Meer informatie over deze plaat</p>
           <div class="price-container"><span class="pricetag">€ 44,<sup>99</sup></span></div>
           <table class="article-specs"><tr><td>Barcode</td><td>0602455866363</td></tr></table>
           <ul class="products"><li><table class="article-specs">
            <tr><td>Barcode</td><td>8719262044807</td></tr></table></li></ul>
          </div><footer>Verzending € 4,99</footer>'''
        result = parse_detail_page(html, listing_payload={'price': '44.99'})
        self.assertEqual(result['ean'], '00602455866363')
        self.assertEqual(result['detail_price_seen'], '44.99')
        self.assertEqual(result['price'], '44.99')

    def test_invalid_or_ambiguous_product_codes_are_rejected(self):
        for values in [('0602455866364',), ('0602455866363', '8719262044807')]:
            rows = ''.join(f'<tr><td>Barcode</td><td>{v}</td></tr>' for v in values)
            html = '<div class="article product-page"><table class="article-specs">' + rows + '</table></div>'
            self.assertIsNone(parse_detail_page(html, listing_payload={})['ean'])


if __name__ == '__main__':
    unittest.main()
