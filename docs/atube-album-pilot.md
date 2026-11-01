# A Tube High Fidelity: read-only album scraper pilot

Two independent, manual Ubuntu workflows:

- `Curedplant | Price | A Tube High Fidelity | Pilot` (`price-atubehighfidelity.yml`)
- `Curedplant | EAN and album detail | A Tube High Fidelity | Pilot` (`ean-detail-atubehighfidelity.yml`)

Both default to two catalogue pages; detail defaults to five articles. Inputs allow 1–10 pages and 1–25 details. There is no schedule, database secret, importer write, shop creation or publication. One concurrency group serializes requests from these two workflows. This pilot uses the registered source route concept, but does not register an exact-product importer that would discard missing-EAN records.

In Actions, open the named workflow, choose **Run workflow**, and download its `atubehighfidelity-*` artifact. `products.csv` contains every discovered row, including exclusions; `result.json` contains source hashes, request evidence, pagination completeness, per-record reasons and detail verification. A successful execution requires eligible listing prices (price mode) or at least one validated detail (detail mode). It does not mean every row is approved.

Local equivalent:

```sh
python -m scripts.scrapers.atubehighfidelity --mode prices --pages 2
python -m scripts.scrapers.atubehighfidelity --mode details --pages 2 --detail-limit 5
python -m unittest discover -s tests -p test_atubehighfidelity.py
```

## Source contract for subsequent album scrapers

Preserve `source_product_id`, `source_url`, full `title_raw`, separate explicitly delimited `artist_raw`/`album_raw`, listing article price, currency and original observation time. Missing/unpriced, CD/DVD/Blu-ray, uncertain identity and used articles remain in the evidence with review reasons. No used signal means new; missing EAN never means used. A category label alone must not override a CD title.

Prices come from each own visible product card, excluding `<del>`, and must agree with its `data-price`. A missing price never becomes zero, shipping cost or another card's price. Detail verification keeps the original listing price and requires an exact crosscheck. Detail stock comes from the own product or selected variant, not a shipping banner. Signed variants require a unique exact option named in the listing, with its own public price/stock and an option-specific offer URL; no cheapest-variant guess.

Barcode checks use own explicitly labelled specifications; SKU, article number, URLs, pictures and related products never become EAN evidence. Labelled invalid/conflicting EANs go to review. A parent barcode is not automatically assigned to a selected variant. `EAN_NOT_CHECKED` means the listing is pending enrichment; `EAN_NOT_FOUND` records absence in the stated checked scope, not proof that an EAN does not exist anywhere. EAN-free detail records use `ARTIST_TITLE`, found valid barcodes use `EAN`. Original labels, signed/physical edition descriptions, and stronger existing EANs remain intact. No album identity or pressing equivalence is invented by this collector.

The shop uses a custom WooCommerce overview: first-page HTML, then the same public `atube_cs_shop_load_more` POST used by its browser, with the page's current public nonce, vinyl filter, offset and native 24-item page size. Endpoint/host are pinned. Pagination rejects repeats, nonadvancing offsets, changed totals and premature endings; a page limit is explicitly marked incomplete. It never claims the whole catalogue was crawled after a bounded pilot. Robots rules are respected (observed five-second request spacing); access errors stop the shop and preserve captured rows. There is no CAPTCHA or access-control bypass.

## Moving beyond the pilot

The existing `album_offer_sources.verify_source` has a dedicated A Tube adapter because this shop has custom HTML and no own Product JSON-LD in the inspected pages. The adapter requires a fresh listing, exact own title/product identity, matching article price and labelled barcode checks. Its queue path is covered by regression tests.

Register and verify the shop and shipping markets, stage captured source rows through the existing album-offer queue, then perform fresh source verification and trusted unique album matching before publication. Route a later discovered EAN to the exact-product path and deduplicate by shop/product/variant URL. Product metadata, EAN identity and price history must never be rewritten just to obtain an album match. The private album queue currently has its own active pilot budget; these public workflows do not bypass it. After reviewing actual results, schedule price and detail runs independently.

The single user-facing progress document remains `Vinylofy/docs/database/album-alternatives-and-price-history.md`. This document defines the reusable source contract, not a separate batch status sheet.
