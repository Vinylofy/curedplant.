# RareVinyl reconnaissance, 3 November 2026

Read-only research. No database writes, scheduling or publication.

- The EU collection HTML and its public `products.json` returned HTTP 200.
- `robots.txt` permits the tested collection and product paths for `User-agent: *`.
- Two pages of 50 listing records each returned 100 distinct Shopify product IDs.
- All 100 had a price and title, and all had a `Sealed` tag; 90 had a
  `WHOLESALENEW` tag. These tags alone do not prove condition or eligibility.
- Listing variants contained no barcode in this sample. Ten sampled product
  `.js` endpoints returned HTTP 200 and a barcode; their prices matched their
  corresponding listing prices. This is a small, non-random sample.
- Three of 100 listing titles included an explicit CD signal. CD/vinyl
  classification needs structured evidence and mixed-format handling.
- The HTML reports active currency EUR. Prices, VAT and delivery for Dutch
  and Belgian destinations remain unverified; no checkout was performed.
- PR #3 head `49c3585b0ce9deefb703992c3fea3bf9a8a28bb0` fails Python
  compilation at line 104 due to literal backslash-n sequences. Its card
  parser also searches a parent text block for a price, and detail parser
  searches the entire page. Neither establishes product-price provenance.
- Vinylofy PR #65 states its Windows diagnostic has not been run. It supplies
  no observed live result and is not needed for the requested Ubuntu setup.
- Artist/title decomposition, condition confirmation, product-specific sale
  price, shipping/market eligibility, staging and matching integration,
  resilient checkpoints and duplicate handling remain to be validated.

Do not activate production writes or schedules until the above gates and
bounded Ubuntu integration tests have passed.

## Second read-only pilot

The new `scripts.scrapers.rarevinyl` reads structured Shopify listing
variants and verifies each detail response against product ID, variant ID,
and listing price. It rejects ambiguous variants, invalid prices, unsafe URLs,
blocked responses, repeated pages and foreign hosts. It uses a two-page and
ten-detail hard limit, with no database credentials, writes or publication.
Observed locally: 100 listings, 100 valid listing prices, 100 sealed signals,
10 detail records, 10 valid GTINs, 90 without a checked barcode, 5 missing
artist or album text, zero duplicate IDs, zero recorded errors. These results
are a bounded sample, not a full-catalogue census.

Every record remains blocked from publication: source evidence and market
prices have not yet passed the NEW-condition and NL/BE eligibility gates.
The research workflow is manually dispatched only; it does not activate a
production scraper, stage records or schedule any job.
