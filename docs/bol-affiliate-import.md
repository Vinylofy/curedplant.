# bol Affiliate feed import — implementation and approval checklist

Status: implemented and locally tested; **not live**. No production writes,
shop registrations, website changes or schedules have been performed. This
document is the central status for this import. The current repository is
`Vinylofy/curedplant.`; `Vinylofy/Vinylofy` was inspected read-only for the
database and website contracts.

## Existing architecture reused

* `scripts/importers/common.py`: strict GS1 check-digit validation, canonical
  GTIN-14 identity, safe EAN/UPC variants, `CanonicalRecord`, existing product
  insertion, price upsert and price history.
* Existing tables: `products`, `shops`, `prices`, `price_history`,
  `raw_shop_scrapes`, `shop_shipping_destinations`. No invented table/RPC and
  no schema migration. SQL contracts were checked against existing importers
  and the website repository migrations. Production schema access was not
  available to verify the deployed version.
* Existing price identity is `(product_id, shop_id)`, not country. A single
  bol shop would overwrite NL with BE. The dedicated importer requires two
  explicitly configured bol shop IDs, each with the correct country. It
  rejects a shop with confirmed visibility in another market. It never calls
  `ensure_shop()`, which looks up by domain and could merge these market shops.
* This is a dedicated affiliate CLI rather than registration in the generic
  `run_import` registry: that writer would bypass the explicit publication
  approval, market isolation and content-source rules of this import.

Existing products are matched by validated barcode only, without modifying
their masterdata. New barcode products use the existing insertion helper with
a neutral `Vinyl <EAN>` placeholder, no artist or cover and the normal
shop-observed metadata review flag. Bol titles stay in `raw_shop_scrapes`,
linked by barcode/source-product ID; descriptions and images are not imported.
Real descriptive masterdata still needs the existing enrichment process.
This choice keeps bol music content removable without deleting another
source's canonical titles/covers. The importer never publishes a bol cover.

## Official source findings (checked 18 October 2026)

| Finding | Evidence / limitation |
| --- | --- |
| Bulk source | [Entertainment group](https://api.bol.com/marketing/docs/product-feed/product-feed-groups.html): `product-feed_entertainment-v2.csv.gz`; pipe-delimited CSV, XML also available. This includes more than vinyl: explicit format filtering is mandatory. |
| Market offers | [Overview](https://api.bol.com/marketing/docs/product-feed/index.html): `OfferNL` and `OfferBE`, one selected best offer per product/market, not every marketplace seller. `sellerType=B` means bol, `P` an external partner; individual seller name/ID is not confirmed. |
| Field evidence | [Official example XSD](https://github.com/devbolcom/bolcom-partnerprogramma-feed-php-example/blob/master/resources/product-1.1.xsd) documents `ean`, `productId`, `title`, `productUrlNL/BE`, `sellingPrice`, `shippingCost`, `condition`, `isDeliverable`, `listPrice`, `sellerType`, and named product properties. It is v1.1 evidence, **not proof of the current v2 account feed headers or value vocabulary**. |
| Actual feed schema | **UNKNOWN** until authenticated download. `config/bol-feed.example.json` is deliberately marked `live_schema_verified=false`. `Properties.Drager`, `NEW`, `LP`, `Vinyl` are test mappings, not claimed observed current account values. First inspect the feed, then validate/amend the profile. |
| Download | [Official instructions](https://api.bol.com/marketing/docs/product-feed/download-product-feed.html): explicit FTPS to `apm-feed.unftp.bol.com:21`, passive mode, TLS data connection. Python verifies the certificate; no downgrade to plain FTP. The downloaded file is temporary and removed after use, including exceptions. |
| Source-IP requirement | [Account access instructions](https://api.bol.com/marketing/docs/product-feed/access-product-feed.html): Account → Productfeed → edit user → add public IPv4. One whitelisted IP by default; allow about one hour after editing. |
| Refresh | Overview says every two hours, available at 01:30, 05:30, 07:30, …, 23:30; 03:30 skipped. No timezone is specified there: confirm before scheduling. A daily import cannot promise the same freshness as a two-hour feed. |
| Content | [Terms](https://affiliate.bol.com/nl/algemene-voorwaarden/): article 3.4 explicitly requires `Copyright Muze UK Ltd` or `© Muze UK Ltd` near music content; 3.6 requires keeping displayed price/availability current; 3.9 limits links to registered channels. API terms allow local content storage and require removal on request/termination. No specific universal 24-hour cache limit was established in these pages. |
| Application scope | Terms mention exclusions including spider/stock-alert sites. Having credentials does not prove approval of Vinylofy's particular registered channel. Confirm the actual approved channel/use; this is not a finding that this comparison website is prohibited. |
| Marketing API | [Catalog overview](https://api.bol.com/marketing/docs/catalog-api/index.html) is the affiliate API, distinct from Retailer API. No API calls, API keys or speculative enrichment are added: no necessary missing field has yet been demonstrated in the real feed. |

## Selection and data rules

* Require explicit configured format and new-condition values; unknown format,
  unknown condition, used/CD/DVD/accessory rows are excluded with a reason.
  Vinyl-primary mixed-media boxsets can be whitelisted by their verified format
  value. No title-only inference and no separate pressing-match gate.
* Preserve barcode strings and leading zeros; normalize EAN/UPC to GTIN-14.
  Existing barcode matches with an explicit CD/DVD/etc. format conflict abort
  the transaction for manual review. Ambiguous product matches also abort.
* Use `sellingPrice`, never `listPrice` or shipping as the article price.
  Unknown shipping remains `null`; known zero is accepted only from a numeric
  source field. Unsupported shipping prose is a rejected offer, not free.
* `isDeliverable` true/false maps to in-stock/out-of-stock; absent/unrecognised
  values remain unknown. This is feed deliverability, not independently
  measured physical inventory or a delivery-date guarantee.
* Missing BE offers stay absent. Country-specific prices/links/seller type and
  shipping are kept independently. Country comes from the offer block and
  validated destination path, never copied from the other market.
* Price/shipping/seller/source timestamp evidence is stored in the existing
  raw payload. There is no verified offer-level shipping or seller column in
  the current public `prices` contract. Those fields therefore cannot yet be
  rendered per offer by the unchanged website.
* Build/validate the whole bounded plan before any DB mutation. A malformed
  feed is fatal; no partial source plan gets written. All selected markets
  commit in one transaction. Newer database prices are preserved. Replaying
  the identical snapshot does not add offers/history/raw evidence.
* Never deactivate missing offers, even after a complete import. The ordinary
  market views' existing 48-hour freshness filter continues to apply. A failed
  or incomplete feed does not deactivate anything. Pilot limits explicitly
  set `complete_feed=false`; they must not be scheduled as full imports.
* FTP MDTM records source file time. Local writes require an explicitly supplied
  aware source timestamp; writes reject future or older-than-six-hour source
  times. MDTM is file modification time, not independently proven feed
  generation time. This limitation must be checked on the live feed.

## Windows runner and safe configuration

Use the existing Windows machine, **not** `windows-latest`. That machine must
have a self-hosted runner registered for `curedplant.` or an organisation runner
that is allowed to serve it. The default labels are `self-hosted`, `Windows`,
`vinylofy-windows`. A repository-specific Vinylofy runner does not automatically
serve curedplant. Do not replace its existing runner service: register an
additional service/work directory if repo-level registration is needed.

An existing Windows machine saves buying a new service, but Windows itself
does not make an ISP's address static. The workflow fails before using bol
credentials if its observed IPv4 differs from the configured allowed address.

GitHub → curedplant. → Settings → Secrets and variables → Actions:

| Type | Name | Value |
| --- | --- | --- |
| Secret | `BOL_FEED_USERNAME` | Actual productfeed account username (not Marketing API client ID) |
| Secret | `BOL_FEED_PASSWORD` | Actual productfeed password |
| Variable | `BOL_SITE_ID` | Site_ID of the approved website channel; NL and BE may use the same channel ID |
| Variable | `BOL_FEED_PUBLIC_IPV4` | Public IPv4 **observed on the Windows runner**, also entered at bol |
| Variable | `BOL_FEED_RUNNER` | Optional custom Windows runner label; default `vinylofy-windows` |
| Variable | `BOL_FEED_PROFILE` | Validated profile path; example defaults to `config/bol-feed.example.json` |

No credentials belong in chat, committed files, command-line arguments or
public URLs. The review workflow receives **no** `DATABASE_URL`. For an
approved local write only, use the existing secret environment convention for
`DATABASE_URL` and `BOL_SHOP_IDS={"NL":"<approved-uuid>","BE":"<approved-uuid>"}`.
Do not put UUID placeholders in a real import invocation.

Current access blocker: this session's GitHub integration returns HTTP 403 for
both Actions-secret administration and self-hosted-runner administration. It
can edit/push repository code but cannot register a runner or configure those
secrets. No feed credentials or actual Site_ID have been supplied. Consequently
the real public IPv4 and account schema are unconfirmed, and no live feed
download has occurred. This is a permissions/configuration blocker, not an
importer test failure.

First manual workflow:

1. Open **Curedplant | Affiliate | bol | Feed review** in Actions. Use
   `ip_check_only=true`. Its summary shows the actual Windows public IPv4.
2. Enter that IP at bol Account → Productfeed → edit user. Set
   `BOL_FEED_PUBLIC_IPV4` to the same IP and store feed credentials in the two
   secrets above. Wait for bol to apply the allowlist.
3. Run with `ip_check_only=false`, `inspect_schema=true`. Review the downloaded
   feed's actual headers/property values; no database is used.
4. Adjust the profile to the verified new/vinyl values and field names. Run
   with `inspect_schema=false`, `limit=20`. Download the review artifact.
   The review artifact retains one day; the bulk feed is never uploaded.

## Commands and approval boundary

From repository root, using a Python environment with `requirements.txt`:

```sh
# Actual source inspection. Credentials are already in the environment.
python -m scripts.importers.bol_feed --profile config/bol-feed.example.json --inspect-schema

# Real bounded dry-run after verifying/amending the profile; zero DB writes.
python -m scripts.importers.bol_feed --profile config/bol-feed.local.json --markets NL,BE --limit 20

# Optional real match counts: read-only SQL, never product/price writes.
python -m scripts.importers.bol_feed --feed /path/to/actual-feed.csv.gz --profile config/bol-feed.local.json --limit 20 --check-matches

# ONLY AFTER the user has approved the live results, shop setup, and visibility:
python -m scripts.importers.bol_feed --profile config/bol-feed.local.json --markets NL,BE --limit 20 --write --approve-publication
```

The final command additionally requires `live_schema_verified=true` in the
reviewed profile and the two market shop IDs. There is deliberately no write
button or schedule in the review workflow. Preview and production use the
same Supabase project, so public prices are public in both environments.
No invisible production staging mode has been proven; therefore the current
delivery stops at dry-run and prepares the explicit public-import command.

Before a public pilot, prepare/review the two shop records with the actual
deployed constraints. No shop domain values have been invented to circumvent
domain uniqueness. The existing `ensure_shop(domain)` helper cannot safely
register two market identities. Exact IDs are supplied to this importer instead.
Inspect the deployed domain constraint and decide the two market identities
before registering them. Keep the new shops inactive and destinations
unconfirmed until publication is approved. No new `Marketplace` enum is
invented: the current shop-type constraint permits only physical record store,
online record store or online retailer. Bol includes partner offers, so any
marketplace badge requires an explicit website classification change.

After the successful public pilot and approval, a separate manual write job
and scheduled FTPS job can use this same CLI. Proposed full refresh is after
each available two-hour feed (or a consciously lower cadence), with single
flight and a Windows IP check. Confirm feed timezone, download volume, actual
catalog size and runtime before selecting cron times. **No automation has
been activated.** Bulk scans default to a million-row safety ceiling; `--limit
0` means all eligible items within that ceiling, not a promise of unlimited
coverage. Inspect `complete_feed` before considering a full-feed schedule.

## Website handoff (no website files changed)

`lib/markets.ts::getEligibleShopIds` and
`market_product_best_prices_v1` use active shops and confirmed
`shop_shipping_destinations`. Confirm only NL for the NL shop and BE for the
BE shop; the shop country alone does not scope visibility. The current
`prices` rows hold affiliate URLs normally. Article-price ranking stays
unchanged: shipping and affiliate commission never alter ranking.

Before launch, register/approve the definitive domain as an affiliate channel
and select its correct Site_ID. Reconfigure that ID independently of database
identity; the importer never references preview.vinylofy.com. No data migration
is needed when the website domain changes, but already stored affiliate URLs
need refreshing if their channel Site_ID changes.

Website work still needed: clearly label purchase at bol, affiliate disclosure,
nearby © Muze UK Ltd where bol music content is shown; preserve existing
content/covers from other sources; decide the marketplace display within the
existing categories; display offer-specific seller/shipping only after an
approved existing-or-new storage/display contract. No link is claimed tested
in a real account: tests validate encoded Site_ID/product/country, not click
attribution in bol reports or user-preference redirects.

## Verified local result

26 targeted tests passed, including 8 actual temporary-PostgreSQL tests:
market isolation/shared products, replay idempotency, preserved newer prices,
preserved masterdata, barcode/CD conflicts, visibility guards, no deactivation
after failed/empty/stale plans; plus CSV/gzip/XML, sale-price authority,
shipping, affiliate encoding, unknown/new/used/format gates and zero-write
dry-run. The temporary database is independent of Supabase and removed after
tests. Actionlint passed with the existing Windows runner-label config.

Synthetic pilot generator: `python tests/bol_demo.py output/bol-synthetic.csv`.
It creates 20 explicitly fictitious products with 40 NL/BE offers. This proves
the processing flow, **not** live feed contents, real matching counts,
production write compatibility or affiliate account attribution. Real feed
and database match counts remain unknown until secure access is configured.
