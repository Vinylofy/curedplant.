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

## Follow-up: destinations and condition

The storefront's own localization form was used in separate sessions for NL
and BE, and the rendered Shopify country confirmed each selection. The same
three product variants showed EUR 54.99, 62.99 and 39.99 in both sessions.
This is a three-product sample of article prices, not a checkout or proof of
all taxes, shipping costs or delivery conditions.

The shop's [shipping information](https://eu.rarevinyl.com/pages/postage-shipping-and-worldwide-delivery)
states that local tax/customs and duty-paid delivery is offered for the
Netherlands; for other countries the available duty/tax-paid service is shown
at checkout and otherwise the customer is responsible for import taxes.
Belgium is not explicitly named in that duty-paid list.

In ten sealed product descriptions the shop's own `Condition` field stated
`Factory sealed from new. This item is unplayed.` Used vinyl and CD samples
included `Excellent condition` or explicit signs of play. The scraper now
recognizes the exact product-specific NEW condition statement; tags such as
`NewInStock` or a sealed banner alone do not prove NEW. A subsequent one-page
pilot returned 50 listings, 10 checked details, 10 explicit NEW vinyl records,
10 valid barcodes, one missing artist/title, no duplicate IDs and zero errors.
All records remain blocked pending destination/checkout and integration checks.
