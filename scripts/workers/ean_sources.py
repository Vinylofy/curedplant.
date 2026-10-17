"""Shop-specific discovery and detail parsers reused by the daily EAN lane.

No native pipeline main(), importer, listing-price sync or delisting function
is called here. Listing pages only supply the queue; detail results are metadata.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import importlib
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from scripts.importers.common import strict_normalize_gtin
from scripts.scrapers.usf.core.site_transport import get_with_browser

BLOCKED = {"northendhaarlem", "soundsvenlo"}
LEGACY = {"atthemovies", "bestkeptrecords", "blackvinyl", "getbackmusic", "rockinoutrecords",
          "topnotch", "vinyleers", "vinylfreaks", "viprecords", "suburban", "recordsonvinyl", "platomania"}
REVIEWED = {"cdhal", "colouredvinyl", "dgmoutlet", "everythingjazz", "fiftiesstore",
            "myrecordstore", "shop3345", "soundshaarlem"}
GREEN = tuple(sorted(LEGACY | REVIEWED | {"bobsvinyl", "platenzaak", "sounds", "variaworld", "imusic", "jpc"}))


def module(name):
    return importlib.import_module("scripts.scrapers." + name)


def link_row(link):
    if is_dataclass(link):
        return {"source_url": link.source_url, "source_product_id": link.source_product_id,
                "payload": link.payload}
    url = link.get("product_url") or link.get("url")
    return {"source_url": url, "source_product_id": str(link.get("product_id") or "") or None,
            "payload": dict(link)}


class EanSource:
    def __init__(self, shop, *, sleeper=time.sleep):
        if shop not in GREEN:
            raise ValueError(f"Shop is not approved for daily EAN collection: {shop}")
        self.shop, self.sleeper, self.last_request = shop, sleeper, None
        self.events = []
        self.session = self._session()

    def _session(self):
        if self.shop == "bobsvinyl":
            return module("bobsvinyl").make_detail_session()
        if self.shop == "platenzaak":
            return module("legacy.platenzaak_legacy").build_session()
        if self.shop in {"imusic", "jpc"}:
            return module(f"usf.jobs.detail_{self.shop}").build_session()
        if self.shop in LEGACY - {"platomania", "recordsonvinyl"}:
            native = module(self.shop)
            for name in ("make_session", "build_session"):
                if hasattr(native, name):
                    return getattr(native, name)()
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                                "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8"})
        if self.shop in {"rockinoutrecords", "vinylfreaks"}:
            # Keep the explicit identity used by the native HTTP workers.
            session.headers["User-Agent"] = {"rockinoutrecords": "Vinylofy-RockinOut-Pilot/1.0",
                                             "vinylfreaks": "Vinylofy-VinylFreaks/1.0"}[self.shop]
        return session

    def get(self, url):
        if self.last_request is not None:
            remaining = (2.0 if self.shop == "cdhal" else 1.0) - (time.monotonic() - self.last_request)
            if remaining > 0:
                self.sleeper(remaining)
        self.last_request = time.monotonic()
        # Retain CDHal's already verified ordinary rendering/429 policy.
        response = get_with_browser(self.session, url, timeout=(10, 30)) if self.shop == "cdhal" else self.session.get(url, timeout=(10, 30))
        if self.shop == "cdhal" and response.status_code == 429:
            self.events.append({"url": url, "status": 429, "retry": "native bounded Retry-After policy"})
            response = module("usf.jobs.detail_cdhal").request_detail_page(self.session, url, max_attempts=2)
        self.events.append({"url": url, "status": response.status_code,
                            "sha256": hashlib.sha256(response.content).hexdigest()})
        response.raise_for_status()
        return response

    def close(self):
        self.session.close()

    def terminal(self, cursor):
        counts = {"soundshaarlem": lambda: len(module("usf.jobs.refresh_soundshaarlem_listing_prices").SEED_URLS),
                  "sounds": lambda: 2,
                  "variaworld": lambda: len(module("usf.jobs.refresh_variaworld_listing_prices").SEEDS),
                  "platomania": lambda: len(module("legacy.platomania_legacy").SEED_URLS)}
        seed = cursor.get("seed", 0) + 1
        if seed >= counts.get(self.shop, lambda: 1)():
            return {"page": 1, "seed": 0, "exhausted": True}
        return {"page": 1, "seed": seed}

    def catalog(self, cursor):
        """Return rows and next cursor; never fetch product detail during discovery."""
        page, seed = cursor.get("page", 1), cursor.get("seed", 0)
        shop, now = self.shop, datetime.now(timezone.utc)
        next_cursor = {"page": page + 1, "seed": seed}
        rows, seeds = [], 1
        if shop in {"imusic", "jpc"}:
            # Their large exposure queues are supplied by the existing source
            # discovery jobs. Do not replace those with an unbounded search crawl.
            return [], {**cursor, "registry_only": True}
        if shop == "fiftiesstore":
            source = module("usf.jobs.refresh_fiftiesstore_listing_prices")
            products = source.fetch_batch((page - 1) * 100, 100).get("product_data", [])
            rows = [{"source_url": source.normalize_url(p["url"]), "payload": {
                "title": p.get("name"), "ean": source.ean_from_sku(p.get("sku")),
                "sku": p.get("sku"), "price": source.price(p.get("price"))}} for p in products]
            if not products:
                next_cursor["exhausted"] = True
            return rows, next_cursor
        if shop == "everythingjazz":
            source = module("usf.jobs.refresh_everythingjazz_listing_prices")
            url = source.listing_url_for_page(page, 100)
            products = self.get(url).json().get("products", [])
            rows = [link_row(link) for p in products if (link := source.parse_product(p, page=page, seen_at=now)[0])]
            if products and not rows:
                return [], next_cursor
        elif shop == "shop3345":
            products = self.get(f"https://3345.nl/products.json?limit=100&page={page}&currency=EUR").json()["products"]
            for p in products:
                title, tags = p.get("title", ""), str(p.get("tags", ""))
                if not re.search(r"\b(?:LP|vinyl|12[ -]?inch|7[ -]?inch)\b", title, re.I):
                    continue
                if re.search(r"\b(?:used|second[ -]?hand|tweedehands)\b", title + " " + tags, re.I):
                    continue
                rows.append({"source_url": "https://3345.nl/products/" + p["handle"],
                             "payload": {"title": title, "currency": "EUR", "is_secondhand": False}})
            if products and not rows:
                # A non-vinyl page is not the end of the complete product feed.
                return [], next_cursor
        elif shop in {"cdhal", "colouredvinyl", "myrecordstore", "soundshaarlem", "sounds", "variaworld"}:
            source = module(f"usf.jobs.refresh_{shop}_listing_prices")
            if shop == "cdhal":
                url = source.listing_url(page)
                parsed = source.parse_listing_page(self.get(url).text, page=page, source_listing_url=url, seen_at=now)
            elif shop == "colouredvinyl":
                url = source.listing_url_for_page(page)
                parsed = source.parse_listing_page(self.get(url).text, page=page, listing_url=url, seen_at=now, debug=False)
            elif shop == "myrecordstore":
                url = source.page_url(page)
                parsed = source.parse_listing_page(self.get(url).text, page=page, listing_url=url, seen_at=now)
            elif shop == "soundshaarlem":
                seeds = len(source.SEED_URLS)
                start = source.SEED_URLS[seed]
                url = start + ("&" if "?" in start else "?") + f"page={page}"
                parsed = source.parse_collection_page(self.get(url).text, seed_url=start, listing_url=url, page=page, seen_at=now)
            elif shop == "sounds":
                sections = ["bestsellers", "nieuw"]
                seeds = len(sections)
                url = f"https://sounds.nl/{sections[seed]}/{page}/lp/all"
                parsed = source.parse_listing_page(self.get(url).text, page=page, listing_url=url, seen_at=now)
            else:
                keys = list(source.SEEDS)
                seeds = len(keys)
                url = source.SEEDS[keys[seed]].format(page=page)
                parsed = source.parse_listing_page(self.get(url).text, seed_key=keys[seed], page=page, listing_url=url, seen_at=now)
            rows = [link_row(link) for link in parsed[0]]
        elif shop == "bobsvinyl":
            source = module("bobsvinyl")
            url = source.collection_page_url(page)
            soup = BeautifulSoup(self.get(url).text, "html.parser")
            rows = [link_row(row) for card in soup.select("div.card-wrapper.product-card-wrapper")
                    if (row := source.parse_listing_card(card, url))]
        elif shop == "platenzaak":
            source = module("legacy.platenzaak_legacy")
            url = source.COLLECTION_URL + f"?page={page}"
            parsed = source.parse_listing_page(BeautifulSoup(self.get(url).text, "html.parser"), page)
            rows = [link_row(asdict(row) if is_dataclass(row) else row) for row in parsed]
        elif shop == "platomania":
            source = module("legacy.platomania_legacy")
            seeds = len(source.SEED_URLS)
            url = source.page_url(source.SEED_URLS[seed], page)
            soup = BeautifulSoup(self.get(url).text, "html.parser")
            rows = [link_row(row) for article in soup.select("article.article")
                    if (row := source.parse_article(article, source.category_name_from_url(source.SEED_URLS[seed]), url, False))]
        elif shop == "recordsonvinyl":
            url = f"https://recordsonvinyl.nl/collections/all?page={page}"
            soup = BeautifulSoup(self.get(url).text, "html.parser")
            rows = [{"source_url": urljoin(url, a["href"]).split("?", 1)[0],
                     "payload": {"title": a.get_text(" ", strip=True)}}
                    for a in soup.select('a.grid-product__link[href*="/products/"]')]
        elif shop == "blackvinyl":
            source = module(shop)
            url = f"{source.STORE_API_URL}?category={source.DEFAULT_CATEGORY_ID}&per_page=100&page={page}"
            response = self.get(url)
            products = response.json()
            if response.headers.get("X-WP-TotalPages") and page >= int(response.headers["X-WP-TotalPages"]):
                next_cursor["exhausted"] = True
            rows = [link_row(source.listing_row(p, page=page, category_id=source.DEFAULT_CATEGORY_ID,
                       category_slug="lp-nieuw", scraped_at=now.isoformat(), source_api_url=url)) for p in products]
        elif shop == "dgmoutlet":
            source = module("dgmoutlet")
            class ListingOnly(source.DGMOutletLPScraper):
                def _fetch(self, url):
                    return ""  # _parse_card's optional detail-stock fallback must not make requests.
            native = ListingOnly("unused.csv", max_pages=1)
            url = source.BASE_URL.format(page=page)
            soup = BeautifulSoup(self.get(url).text, "html.parser")
            for card in soup.select("div.card.product-box.box-standard"):
                row = native._parse_card(card, page, url, now.isoformat())
                if row:
                    payload = asdict(row)
                    payload.update(price=row.price_current, title=row.raw_name)
                    rows.append({"source_url": row.url, "payload": payload})
        else:
            source = module(shop)
            if shop == "atthemovies":
                url = source.DEFAULT_COLLECTION_URL + f"?page={page}"
                parsed = source.parse_listing_page(self.get(url).text, collection_url=url)
            else:
                if shop == "rockinoutrecords":
                    url = source.CATEGORY_URL if page == 1 else source.CATEGORY_URL + f"page/{page}/"
                elif shop == "vinylfreaks":
                    url = source.CATEGORY_URL if page == 1 else source.CATEGORY_URL + f"page/{page}/"
                elif shop == "viprecords":
                    url = source.LISTING_URL + f"?page={page}"
                else:
                    url = source.listing_page_url(page)
                parsed = source.parse_listing_page(self.get(url).text, page)
            rows = [link_row(row) for row in (parsed[0] if isinstance(parsed, tuple) else parsed)]
        rows = [row for row in rows if row.get("source_url")]
        signature = hashlib.sha256("\n".join(sorted({row["source_url"] for row in rows})).encode()).hexdigest()
        if not rows or signature == cursor.get("signature"):
            next_cursor = {"page": 1, "seed": seed + 1}
            if seed + 1 >= seeds:
                next_cursor.update(seed=0, exhausted=True)
        else:
            next_cursor["signature"] = signature
        return rows, next_cursor

    def detail(self, row):
        shop, url, payload = self.shop, row["source_url"], row.get("payload") or {}
        title = payload.get("title_raw") or payload.get("title") or payload.get("raw_name")
        result = {"title": title, "domain": urlparse(url).hostname.removeprefix("www."),
                  "is_secondhand": str(payload.get("is_secondhand", "false")).lower() in {"true", "yes", "ja", "1"}}
        if shop in {"everythingjazz", "atthemovies", "recordsonvinyl"}:
            response = self.get(url.rstrip("/") + ".js")
            data = response.json()
            variants = data.get("variants") or []
            if payload.get("variant_id"):
                variants = [v for v in variants if str(v.get("id")) == str(payload["variant_id"])]
            if shop == "everythingjazz":
                native = module("usf.jobs.detail_everythingjazz")
                parsed = native.parse_detail(link=row, payload=data, detail_url=response.url)
                raw = parsed["ean_raw"]
                result["title"] = parsed["title_raw"]
            else:
                codes = {strict_normalize_gtin(v.get("barcode")) for v in variants} - {None}
                raw = next(iter(codes)) if len(codes) == 1 else None
                result["issue"] = None if raw else "missing_or_ambiguous_variant_gtin"
                result["title"] = data.get("title") or title
        else:
            response = self.get(url)
            html, soup = response.text, BeautifulSoup(response.text, "html.parser")
            if shop in REVIEWED:
                # Only the reviewed parsers' source-scoped pure helpers below.
                if shop == "cdhal":
                    parsed = module("usf.jobs.detail_cdhal").parse_detail_html(html, source_url=url, payload=payload)
                    raw, result["title"] = parsed["ean_raw"], parsed["title_raw"]
                elif shop == "colouredvinyl":
                    parsed = module("usf.jobs.detail_colouredvinyl").parse_detail(html=html, source_url=url, listing_payload=payload)
                    raw, result["title"] = parsed["ean"], parsed["title_raw"]
                elif shop == "myrecordstore":
                    native = module("usf.jobs.detail_myrecordstore")
                    raw = native.extract_ean(soup, native.clean(soup.get_text(" ", strip=True)))
                elif shop == "shop3345":
                    raw = module("usf.jobs.detail_shop3345").extract_ean(html, url)
                elif shop == "soundshaarlem":
                    native = module("usf.jobs.detail_soundshaarlem")
                    parsed = native.parse_product_page(html, url, payload)
                    raw, result["title"] = parsed["ean_raw"], native.title_raw_from_detail(parsed, payload)
                elif shop == "fiftiesstore":
                    values = [payload.get("ean")]
                    for tr in soup.select("table#product-attribute-specs-table tr"):
                        label, value = tr.select_one("th"), tr.select_one("td")
                        if label and value and re.search(r"\b(?:ean|barcode|gtin)\b", label.get_text(), re.I):
                            values.append(value.get_text(strip=True))
                    codes = {strict_normalize_gtin(v) for v in values} - {None}
                    raw = next(iter(codes)) if len(codes) == 1 else None
                else:  # DGM's proved product SKU belongs to the same product URL.
                    raw = payload.get("ean")
            elif shop in {"imusic", "jpc"}:
                parsed = module(f"usf.jobs.detail_{shop}").parse_offer(html, final_url=response.url, status_code=response.status_code)
                raw, result["title"] = parsed.ean, parsed.title_raw
                result["image_url"] = parsed.image_url
            elif shop in {"sounds", "variaworld"}:
                native = module(f"usf.jobs.detail_{shop}")
                raw, result["title"] = native.extract_ean(html), native.extract_title(html) or title
            elif shop == "platenzaak":
                details = module("legacy.platenzaak_legacy").extract_detail_table(soup)
                raw = details.get("ean")
                result.update(details=details)
            elif shop == "bobsvinyl":
                valid, raw, used, issue = module(shop).parse_detail_result(soup)
                if not valid:
                    raise ValueError(f"Bob product page failed identity validation: {issue}")
                result["is_secondhand"] = str(used).lower() in {"yes", "ja", "true", "1"}
            elif shop == "platomania":
                parsed = module("legacy.platomania_legacy").parse_details_from_content(soup)
                raw = parsed.get("ean")
                result["details"] = parsed
            elif shop == "blackvinyl":
                value = module(shop).detail_ean_from_html(html)
                codes = {strict_normalize_gtin(value[0]) if value else None,
                         strict_normalize_gtin(payload.get("ean"))} - {None}
                raw = next(iter(codes)) if len(codes) == 1 else None
            elif shop == "suburban":
                parsed = module(shop).extract_detail_page(html)
                raw = parsed.get("ean")
                result["details"] = parsed
            else:
                parsed = module(shop).parse_detail_page(html, url) if shop == "vinylfreaks" else module(shop).parse_detail_page(html)
                raw = parsed.get("ean") if isinstance(parsed, dict) else parsed
                if isinstance(parsed, dict):
                    result["details"] = parsed
            h1 = soup.select_one("h1")
            result["title"] = result.get("title") or (h1.get_text(" ", strip=True) if h1 else None)
        result.update(ean=strict_normalize_gtin(raw), detail_url=response.url,
                      detail_sha256=hashlib.sha256(response.content).hexdigest())
        return result
