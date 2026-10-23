# Bol NL Marketing API prices

The API is the working HTTPS price source while the separate FTPS feed is
unreachable. Verified live on 23 October 2026: product lookup and the
`/marketing/catalog/v1/products/{ean}/offers/best?country-code=NL` endpoint.
The product response's embedded offer omits condition. The best-offer response
supplies `ean`, `countryCode`, `condition`, `isPreOrder`, `price`, `url` and
delivery metadata. Import **best-offer** data, not an assumed NEW embedded offer.

## Data contract

- Only existing products with validated GS1 identity and explicit existing vinyl
  format are considered. No new products, descriptive masterdata or covers.
- Response EAN must match canonical GTIN; country must explicitly be NL and
  condition must be `NEW`. Missing/used conditions are excluded.
- `price` is the article price in EUR. `listPrice` and shipping are never used
  as article price. No verified shipping/seller fields: both remain unknown.
- Preorder is explicit. `Op voorraad.` delivery text means in stock; longer
  delivery text stays unknown rather than claiming physical stock.
- Links must resolve to a canonical NL Bol product path, then use `BOL_SITE_ID`
  for our affiliate channel. Redirects in authenticated HTTP calls are refused.
- Only existing NL shop `f08437c2-1d85-47a6-94f9-33a55612d5cc` is used. Its NL
  identity and confirmed shipping exposure are checked by the common publisher.
  BE responses are diagnostic only: no separate registered BE shop exists.
- Source failures, 401/403/429, malformed responses and widespread market/URL/
  identity errors prevent the whole batch from publishing or advancing.
- A 404 never becomes a fake zero price or an unlisting. Such products advance
  the cursor and are checked again on the next catalogue pass.
- The existing transactional publisher protects newer prices, records history
  and raw evidence, verifies before commit and independently after commit.
  `existing_only=True` also prevents product insertion if a target disappears.

## Operation

Use `.github/workflows/price-bol-api.yml` with secrets `DATABASE_URL`,
`BOL_API_CLIENT_ID`, `BOL_API_CLIENT_SECRET`, and variable `BOL_SITE_ID`.
`write=false` makes no database/progress writes. `sample=true` checks only the
fixed verification EANs and never advances the production catalogue cursor.
Writes require main. The sample and a 100-product catalogue batch were written
and independently verified on 23 October 2026. The catalogue cursor was saved
after the successful batch.

Full catalogue work is bounded to 1–2000 products/run and resumes in UUID order
using `state/bol-api/nl.json`. Only a successful full batch advances state; the
workflow commits the cursor to main after verified database writes. A failed
cursor commit may recheck the same batch, never skip it. Normal website freshness
rules remain unchanged. No source failure refreshes timestamps speculatively.

Rate is at most four catalogue request starts/second, sequentially. One token
is reused until its supplied lifetime approaches expiry, then refreshed; HTTP
failures never trigger blind reauthentication. No raw tokens or credentials are
logged. Run reports contain canonical existing titles, EANs, actual prices,
condition, availability, public product links and verification counts.

The five user-facing example prices are API observations at a specific time.
A blocked browser fetch is not independent verification of the displayed website
price; provide product links for manual comparison, including the same EAN/new
condition and excluding delivery charges.

## Active schedule

The NL workflow checks up to 1000 existing products every half hour (UTC minutes
7 and 37). Manual runs default to a no-write sample. At the observed catalogue
size of 69,529 candidates, a first pass needs about 35 hours at nominal cadence;
GitHub scheduling delays and source failures can extend this. This is gradual
coverage, not a claim that the entire catalogue is already imported.

Live verification evidence:
- Sample dry run: 39930982782, 10 checked, 8 eligible NEW offers, no writes.
- Sample write: 39931073393, 8 prices, independently committed-verified.
- Catalogue pilot: 39931644421, 100 checked, 74 committed-verified, 26 no-offer
  responses. Public REST subsequently exposed 81 distinct Bol prices (one pilot
  target overlapped the sample). The UPC conversion preserves validated GTIN.
