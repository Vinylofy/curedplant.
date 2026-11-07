# bol Affiliate Productfeed via FTPS

The existing importer is `scripts/importers/bol_feed.py`. Live connectivity,
authentication, download and full schema inspection succeeded on the existing
self-hosted Windows runner on 7 November 2026. The explicitly approved NL pilot
published twenty offers and twelve new products; production replay made no writes.
The complete catalogue/API handover remains blocked by the findings in the report.
See [the implementation report](bol-ftps-migration-report.md) for measured
results and the current production-readiness decision.

The [Marketing API updater](bol-marketing-api.md) remains the active source.
Official references: [download instructions](https://api.bol.com/marketing/docs/product-feed/download-product-feed.html),
[feed overview](https://api.bol.com/marketing/docs/product-feed/index.html) and
[Entertainment group](https://api.bol.com/marketing/docs/product-feed/product-feed-groups.html).

## Observed source contract

The full Entertainment CSV contains 902,918 rows in the inspected snapshot.
It is UTF-8, pipe-delimited and gzip compressed. The official endpoint is
`apm-feed.unftp.bol.com:21`: explicit FTPS, verified TLS certificates, passive
mode and `PROT P` are mandatory. There is no plain FTP or Marketing API fallback.

| Meaning | Observed field / value |
| --- | --- |
| Barcode | `ean`; validated GS1 check digit, matched using existing GTIN variants |
| Source product | `productId` |
| Album title / performer | `title` / `Performer`; source evidence only |
| Medium | `Format`, not the previous speculative `Properties.Drager` |
| Accepted vinyl | `LP`, `7" Vinyl`, `12" Vinyl`, `10" Vinyl`, `LP + downloadcode` |
| New condition | `OfferNL.condition` / `OfferBE.condition` = `new` |
| Consumer price | `OfferNL.sellingPrice` / `OfferBE.sellingPrice`; never `listPrice` |
| Deliverability | `OfferNL.isDeliverable` / `OfferBE.isDeliverable`: `Y` / `N` |
| Shipping | Market-specific `shippingCost`; numeric zero is known free, blank is unknown |
| Product link | `productPageUrlNL` / `productPageUrlBE`, not `productUrlNL/BE` |
| Seller class | `sellerType`: `B` / `P`; no individual seller identity is claimed |
| Source time | FTP MDTM, UTC; file modification time, not independently verified generation time |

`EP (Mini Album)` alone does not establish a vinyl carrier. Mixed CD/DVD/Blu-ray
bundles remain excluded. Unknown condition, format and availability values do
not imply NEW, vinyl or in-stock. CD, DVD, cassette and used offers are excluded.

`config/bol-feed.example.json` keeps `live_schema_verified=false`. A live profile
may mark only the separately validated markets in `verified_markets`; the CLI
refuses publication to any other market. The inspection workflow never promotes
an inspected schema automatically. Future or unrecognised release dates prevent
`Y` from claiming current stock; explicit `N` remains out-of-stock.

## Matching, prices and content

Existing barcode products retain all canonical titles, artists, MusicBrainz
metadata and covers. New valid barcodes use the existing `_insert_product`
contract with neutral `Vinyl <EAN>` placeholders and metadata review enabled.
No bol images or descriptions are imported. The regular enrichment pipeline
remains responsible for descriptive masterdata and covers.

The price identity remains `(product_id, shop_id)`. NL reuses the existing
Marketing API bol shop `f08437c2-1d85-47a6-94f9-33a55612d5cc`. No duplicate shop
is created. BE requires its own explicitly validated shop ID and destinations;
no BE shop is created or activated by this migration. Confirmed cross-market
shop exposure is rejected.

Conflicting source offers for one GTIN/market are quarantined. With the live profile,
read-only preflight quarantines ambiguous existing barcodes and canonical carrier
conflicts before any publication. A new conflict occurring after preflight still
aborts the affected transaction. Product-link country and
source product ID must agree. Affiliate links encode the approved `BOL_SITE_ID`.

The controlled writer reuses the existing `products`, `prices`, `price_history`
and `raw_shop_scrapes` contracts. Its shared transaction-level advisory lock is
also used by the current API writer. All markets of each bounded product batch commit together. Full runs use at most
250 products per transaction with pipelined versions of the same shared contracts;
a failure preserves earlier committed-batch progress and never advances the full
checkpoint. Pilot/API single transactions keep their existing scope. Newer stored
prices are preserved; repeated identical snapshots produce no writes; unchanged
price/availability produces no duplicate history even across calendar dates.
A complete feed is required for a requested full publication. Missing offers
never delete or deactivate products/prices.

Shipping and seller evidence remain in existing raw payloads. No verified
per-offer shipping/seller frontend column is invented. The existing website
continues to consume the existing prices and affiliate URLs. Actual post-pilot
Supabase/frontend checks remain mandatory.

## Transfer and automation safeguards

The importer records source time, SHA-256, compressed/uncompressed byte counts,
processing duration and rejection counts. Full gzip integrity is checked before
even a bounded pilot. The source MDTM must remain unchanged during transfer.
Only temporary network/FTP failures are retried, at most three attempts, with
bounded backoff; credentials, certificate failures and invalid data are not retried.

Publications reject future sources and sources older than six hours. Full
production runs can use `--state`: only a successful, complete, committed import
advances an atomic local checkpoint. An unchanged, still-fresh MDTM then skips
RETR and database writes. Profile, markets, channel, shop or database changes
invalidate that checkpoint. Failed or partial runs never advance it.

Both FTPS workflows share concurrency group `bol-feed`, without cancelling an
in-progress run. Every runner invocation checks public IPv4 against
`BOL_FEED_PUBLIC_IPV4` before using feed credentials. Existing secrets are reused;
credentials are never command-line arguments or raw exception logs. Bulk files
are temporary and removed; only review evidence is uploaded, retained one day.
Windows reports explicitly use UTF-8.

## Review workflow: zero production writes

`.github/workflows/bol-feed-review.yml` runs on the existing Windows runner.

1. `inspect_schema=true`: inspect headers, bounded vocabulary and up to twenty
   candidate vinyl records. Reports whether the full source was traversed.
2. `inspect_schema=false`, `limit=0`, `validation_suite=true`,
   `check_matches=true`: one download, a 20-product dry-run and a full scan.
   Database identity/price comparisons use read-only, repeatable-read batches
   of 500 GTINs. Each requested market has separate reported counts.
3. `inspect_inventory=true`: protected FTPS filenames, sizes, timestamps and
   bounded supplemental CSV headers; no complete-file claim from a header probe.

The review workflow receives `DATABASE_URL` only when match checks are requested
and schema inspection is off. Review code never calls the writer. The existing
NL shop ID is used only to compare its current prices. BE prices are not
compared with the NL shop.

## Publication workflow: explicit approval

`.github/workflows/bol-feed-import.yml` provides these modes:

- `dry_run`: twenty products, read-only database matching.
- `diagnose_writer`: Ubuntu read-only database plans/indexes/locks/settings; no
  feed login. Reports no driver messages or SQL parameters.
- `audit_catalogue`: read-only comparison of a completed full review with the
  existing catalogue; optional bounded API classification samples.
- `audit_supplemental`: one-off complete Dutch Books and Sound Vision scans,
  limited to existing EANs missing from a trusted successful primary review
  (`audit_review_run_id`). Uses the same importer, strict vinyl/NEW rules and
  two-GB compressed-file guard. Rejects publication, creates no products and
  records per-file integrity/source times. Cross-file conflicting offers are
  excluded. This is not part of the automatic two-hour download chain.
- `pilot_review_write`: recover the same approved <=20 NL selection from the
  trusted completed main pilot artifact, with checksum and full identity/link
  validation, through the existing writer. This manual recovery does not change
  the Windows requirement for scheduled FTPS downloads.
- `pilot_write`: at most twenty products, NL only; requires `main`, the verified
  live profile, explicit `approve_publication=true` and the SHA-256 of the reviewed
  snapshot. A changed feed is rejected before any database access.
- `full_write`: additionally requires the automatic API chain configuration
  `enabled=false` and no unfinished API workflow runs. Uses the successful-run
  checkpoint under the Windows service account's `LOCALAPPDATA`.

**Public pilots require explicit user approval; the recorded twenty-product NL pilot has that approval and succeeded.**
The pilot is public; there is no invisible production staging mode.

A two-hour publishing schedule (`15 */2 * * *`, UTC) exists, but its job is
blocked unless BOTH `BOL_FTPS_AUTOMATION_ENABLED=true` and
`BOL_FTPS_PRODUCTION_APPROVED=true` are set. Neither variable is enabled by this
implementation. The official documentation describes two-hour refreshes;
actual refresh phase/timezone still needs multiple observed MDTM snapshots.
The schedule polls rather than asserting an exact feed-generation time.

## Automatic read-only shadow

`bol-feed-shadow.yml` polls every two hours (`15 */2 * * *`, UTC) and dispatches
only the existing full no-write review. Its versioned policy is
`config/bol-feed-automation.json`: `mode=shadow`, `publication_allowed=false`.
The dispatcher has no database/feed credentials and the review has no write input.
A completed full review records a separate source/profile/code/mode-bound Windows
checkpoint. Unchanged sources are skipped without a bulk download. That marker
cannot authorize publication or replace the full-writer checkpoint. The main
dispatch chain has been checked end-to-end: a full read-only review succeeded,
then an unchanged-source run skipped the bulk download in 0.406 seconds. See
[the recorded evidence](bol-ftps-shadow-evidence.json).

Before any full write the current source must cover every current visible,
API-eligible bol offer; unresolved gaps block the writer before mutation. The
source audit explains missing rows and can check a bounded API/category sample.
Only public carrier/category facts are retained; no images/descriptions/tokens.

## Controlled handover and recovery

After explicit pilot approval, merge/review the code, publish twenty NL products
and verify the actual committed rows, frontend prices, availability and affiliate
links. Review real new-product counts and masterdata preservation. Before enabling
full automation, resolve critical conflicts, measure full-writer throughput and
transaction duration against the runner timeout, and establish current Marketing API
coverage parity, including the API's separate preorder classification; `Y` only
proves feed deliverability and does not establish equivalent preorder semantics.
FTPS discovery of new EANs alone does not establish that every
previous API offer is present in the feed.

Only after the verified pilot and the remaining acceptance conditions, set
`config/bol-price-cycle.json` to `enabled=false`, allow queued/running API jobs to
finish, run an approved full FTPS publication and validate it. Then approve and
enable the FTPS schedule. The existing automatic API config is not changed by
this implementation. API credentials, source code, cursor and price history are
retained.

Recovery: first disable FTPS automation and drain its active run; investigate
committed evidence, then explicitly restore the existing API chain configuration
and use its existing controlled resume procedure. Never run two automatic price
sources concurrently. A rejected/failed download preserves existing prices.

## Local checks

Run the targeted bol tests from the repository root. Integration tests require
a disposable loopback PostgreSQL configured with `BOL_TEST_DATABASE_URL`; they
create/drop only their own test database. They never connect to Supabase.
Use actionlint on both FTPS workflows and `git diff --check` before review.
