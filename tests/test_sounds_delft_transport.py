from datetime import datetime, timezone

from scripts.scrapers.usf.jobs import refresh_sounds_listing_prices as sounds


HTML = """
<div class="product-details">
  <a href="/detail/123/lp/artist/album">Artist - Album</a>
  <span class="product-price">€ 24,99</span>
</div>
"""


def test_sounds_uses_canonical_www_host_and_browser_navigation_headers():
    assert sounds.BASE_URL == "https://www.sounds.nl"
    assert sounds.BROWSER_HEADERS["User-Agent"].startswith("Mozilla/5.0")
    assert "text/html" in sounds.BROWSER_HEADERS["Accept"]


def test_listing_parser_keeps_price_and_canonical_product_url():
    links, offers = sounds.parse_listing_page(
        HTML,
        page=1,
        listing_url="https://www.sounds.nl/nieuw/1/lp/all",
        seen_at=datetime.now(timezone.utc),
    )
    assert len(links) == 1
    assert len(offers) == 1
    assert links[0].source_url == "https://www.sounds.nl/detail/123/lp/artist/album"
    assert offers[0].price == "24.99"
    assert offers[0].shop_domain == "sounds.nl"
