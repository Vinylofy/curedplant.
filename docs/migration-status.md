# Vinylofy → Curedplant migration

Source repository: `Vinylofy/Vinylofy`
Target repository: `Vinylofy/curedplant.`

The Ubuntu scraper source tree is copied into `scripts/scrapers/`. The new
Actions lanes are intentionally separate:

| lane | workflow | purpose | default |
|---|---|---|---|
| catalog price | `price-<shop>.yml` | listing/catalog prices | dry-run |
| EAN/detail | `ean-detail-<shop>.yml` | detail pages and EAN enrichment | dry-run |

Each scraper has one price Action and one EAN/detail Action. Each has its own
manual run; approved workers are scheduled independently, so a slow or broken
scraper does not block another.
The database write flag is explicit; schedules are configured to write because
these are the production Ubuntu replacements, while manual runs default to a
dry-run for verification.

EAN automation is now configured per approved shop: 26 daily jobs, maximum
100 previously unprocessed product details per shop and Amsterdam day. Manual
EAN runs default to `write=false`. Two blocked EAN actions have no schedule.
See [the central EAN quality and schedule status](ean-quality-status.md) for
exact times, durable progress, evidence and limitations. There is no global
`CUREDPLANT_SCHEDULE_ENABLED` gate in these workflows; the individual workflow
cron and write input control execution.

Price schedules are independent and were not changed by this EAN rollout.
Windows counterparts are not retired automatically. Disable a counterpart
only after its own replacement has a successful run with verified output.

The repository must have these Actions secrets before a write run:

- `DATABASE_URL`

No secret values are copied between repositories.

## Price rollout: 18 October 2026

All 28 price workers follow `write=false` first, then reviewed `write=true`,
then independent price scheduling and Windows retirement. Pending or blocked
price workers remain unscheduled. EAN schedules are unchanged.
Only a verified dry-run may proceed to `write=true`. Only a successful write
with committed database price verification may enable its daily schedule
and retire the corresponding Windows price execution.

Native listing parsers remain shop-specific. Price runs fetch live listings,
never detail pages. Evidence is uploaded as `price-evidence-<shop>-<run-id>`,
including all listing records, validated prices and a summary. The native
collector receives no database credential. A separate transaction updates only
existing offers by the registered shop and product URL, preserves unknown
availability, records price changes in history and verifies committed values.
It never creates products/offers, writes EANs or publishes covers.

| Shop | Dry-run | Write verification | Price schedule UTC | Windows price |
|---|---|---|---|---|
| atthemovies | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108332388); 821 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108901216); 801 DB verified; 2 ambiguous URLs excluded | `0 2 * * *` | already retired; no scheduled Windows counterpart |
| bestkeptrecords | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108332586); 21534 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39109297452); 4678 DB verified | `7 2 * * *` | already retired; no scheduled Windows counterpart |
| blackvinyl | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108333047); 239 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108675172); 182 DB verified | `14 2 * * *` | already retired; no scheduled Windows counterpart |
| bobsvinyl | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108332554); 9678 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39109091812); 4047 DB verified; 41 ambiguous URLs excluded | `21 2 * * *` | schedule stopped; manual backup retained |
| cdhal | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108538895); 3579 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39109297290); 2148 DB verified | `28 2 * * *` | schedule stopped; manual backup retained |
| colouredvinyl | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108334616); 1160 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108674956); 943 DB verified | `35 2 * * *` | schedule stopped; manual backup retained |
| dgmoutlet | [success](https://github.com/Vinylofy/curedplant./actions/runs/39109118972); 817 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39109297351); 743 DB verified | `42 2 * * *` | schedule stopped; manual backup retained |
| everythingjazz | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108335262); 1468 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108675352); 1299 DB verified | `49 2 * * *` | schedule stopped; manual backup retained |
| fiftiesstore | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108813336); 337 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39109094961); 222 DB verified | `56 2 * * *` | schedule stopped; manual backup retained |
| getbackmusic | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108336474); 6431 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108676808); 4485 DB verified | `3 3 * * *` | schedule stopped; manual backup retained |
| imusic | [success](https://github.com/Vinylofy/curedplant./actions/runs/39109544608); 5925 priced | [success](); 2769 DB verified | `10 3 * * *` | schedule stopped; manual backup retained |
| jpc | [success](https://github.com/Vinylofy/curedplant./actions/runs/39111222968) | [success](https://github.com/Vinylofy/curedplant./actions/runs/39146564774); 14,848 DB verified, 2,961 changed; 7,945 unmatched skipped | `17 3 * * *` daily write | listing/price cron stopped; manual backup retained |
| musiconvinyl | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108338648); 1021 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108676893); 852 DB verified | `24 3 * * *` | price cron stopped; separate Windows detail cron retained |
| myrecordstore | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108339208); 282 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108677067); 32 DB verified | `31 3 * * *` | schedule stopped; manual backup retained |
| northendhaarlem | [failure](https://github.com/Vinylofy/curedplant./actions/runs/39108339265); 0 priced; HTTP403 on first category coloured-vinyl; native transport stops on access denial | not started | off; pending verification | unchanged |
| platenzaak | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108339714); 4830 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108676960); 3571 DB verified | `45 3 * * *` | schedule stopped; manual backup retained |
| platomania | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108340524); 5670 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108678248); 5551 DB verified | `52 3 * * *` | schedule stopped; manual backup retained |
| recordsonvinyl | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108341425); 25025 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39110734445); 8637 DB verified | `59 3 * * *` | schedule stopped; manual backup retained |
| rockinoutrecords | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108341645); 329 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108678475); 114 DB verified | `6 4 * * *` | schedule stopped; manual backup retained |
| sounds | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108341612); 14741 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39109711911); 1950 DB verified | `13 4 * * *` | schedule stopped; manual backup retained |
| soundshaarlem | [success](https://github.com/Vinylofy/curedplant./actions/runs/39111723436); 15028 priced | [success](); 1394 DB verified | `20 4 * * *` | schedule stopped; manual backup retained |
| soundsvenlo | [failure](https://github.com/Vinylofy/curedplant./actions/runs/39108343561); 50 priced; HTTP403 on vinyl page2; first50 records alone do not prove complete pagination | not started | off; pending verification | unchanged |
| suburban | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108343856); 2994 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39109093465); 2133 DB verified; 1 ambiguous URLs excluded | `34 4 * * *` | schedule stopped; manual backup retained |
| topnotch | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108343715); 384 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108678776); 299 DB verified | `41 4 * * *` | schedule stopped; manual backup retained |
| variaworld | [success](https://github.com/Vinylofy/curedplant./actions/runs/39109612069); 15597 priced | [success](); 4468 DB verified | `48 4 * * *` | schedule stopped; manual backup retained |
| vinyleers | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108345614); 2840 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108678694); 654 DB verified | `55 4 * * *` | schedule stopped; manual backup retained |
| vinylfreaks | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108345743); 1022 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108679668); 227 DB verified | `2 5 * * *` | schedule stopped; manual backup retained |
| viprecords | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108346093); 2827 priced | [success](https://github.com/Vinylofy/curedplant./actions/runs/39108903024); 2610 DB verified; 1 ambiguous URLs excluded | `9 5 * * *` | schedule stopped; manual backup retained |

Independent public product-page checks: 20 matched source prices. These are samples, not a claim that every product was individually inspected.

Schedules follow the daily cron convention (`*` day of month). UTC times are shown above. A green price run means the current listing source passed validation and the listed existing price rows were independently read back after commit. New/unmatched offers are left to the separate EAN/product pipeline; no products are created by this price worker. Isolated ambiguous URL-to-product mappings are quarantined without modifying their prices; over 10% ambiguous matched URLs stops the shop.

Mixed Windows pipelines are retired only for shops whose daily Ubuntu EAN lane is already approved. Dedicated Windows EAN workflows remain unchanged. Music On Vinyl keeps its Windows detail cron while the new manual Curedplant EAN worker is being verified; that worker now includes its own bounded catalog discovery. Manual Windows backups remain available.

### Music On Vinyl EAN repair: 18 October 2026

The new `ean-detail-musiconvinyl.yml` workflow is manual only, defaults to
25 products and `write=false`. It has independent bounded discovery from the
same global `/products.json` catalog route used by the native source. Explicit
`product_type=Vinyl` is required; used/CD/merchandise entries are excluded.
The normal lane selects only unprocessed products. The optional `source_pilot`
mode deliberately verifies current products even if already known, without
database access or durable checkpoint reads/writes. It cannot be combined
with writes. The wrapper automatically uses the normal new-only path for a
requested write, never source-pilot replay.

The product parser now reads real whitespace around the visible Barcode (EAN)
label in the main product information container, validates the GS1 check digit,
and rejects conflicting own-product identifiers. Related product cards and
numeric SKUs are not accepted as product EANs. The same parser repair is pushed
to the original Vinylofy repository; the Windows detail cron is retained.

| Verification | Observed result |
| --- | --- |
| Local native-source pilot | 98 explicit vinyl rows from one 100-product collection page; 3/3 actual detail EANs found, including Imagine / Armin van Buuren. This was a source sample, not database matching or publication. |
| [Initial new-only dry-run](https://github.com/Vinylofy/curedplant./actions/runs/39150760074) | No eligible unfinished products; outcome waiting. A green Actions job is not counted as a completed EAN source proof. |
| [First explicit source pilot](https://github.com/Vinylofy/curedplant./actions/runs/39151072143) | 25 attempted, 13 valid GTINs, 12 HTML 404s. The initial unavailable classification was withdrawn: at least one of those URLs returns HTTP 200 locally, so global removal is not proven. |
| [Follow-up source pilot](https://github.com/Vinylofy/curedplant./actions/runs/39151350374) | Stopped after 6 attempts: 3 valid GTINs, 3 technical errors. For these URLs, the hosted runner receives 404 from both HTML and the ordinary product `.js` endpoint. No products marked removed; no database writes, no progress changes. Overall source status red. |

The public `.js` fallback is attempted only after HTML 404, not after 403/429.
It verifies the listing product ID and selected variant ID before accepting a
barcode. If the fallback also fails, this remains a technical failure, never
a successful missing-EAN result.

### Native transport restored and verified: 18 October 2026

The controlled Linux/Windows comparison used the same three vinyl URLs and
requests 2.34.2. Native MOV headers with a fresh session per detail returned
three HTTP 200 responses and all three visible barcodes on both runners. The
Linux generic shared catalog/detail session returned two false 404s. Keeping
the generic headers but isolating sessions returned 200s with differing HTML.
This proves the native profile/session combination works; the individual
cookie/header responsible was not isolated. Evidence:
[Linux comparison](https://github.com/Vinylofy/curedplant./actions/runs/39152045638)
and [Windows comparison](https://github.com/Vinylofy/curedplant./actions/runs/39152285395).
The Linux comparison job succeeded; its overall run failed during the first
Windows bootstrap, corrected in the separate successful Windows comparison.

Commit `6892d87` restores `musiconvinyl.make_session()` and opens/closes a fresh
native session for every product HTML/JSON request. Catalog requests retain
their separate native session. Request spacing and explicit error reporting
are preserved; the other shop transports are unchanged.

[Hosted 25-product source proof](https://github.com/Vinylofy/curedplant./actions/runs/39152893138):
**25 attempted, 25 valid GTINs, zero missing EANs, zero technical errors**.
All 26 HTTP requests returned 200. Every accepted EAN came from the visible
own-product Barcode (EAN) field, scoped and check-digit validated. No database
or progress writes were performed. Targeted local validation: 36 passing tests
(14 MOV, 17 orchestration, 5 other adapters), plus actionlint and diff checks.

The bounded normal new-only write verification
[39153045523](https://github.com/Vinylofy/curedplant./actions/runs/39153045523)
completed without errors: 10 catalog pages, all HTTP 200, but zero eligible
unfinished products. Its actual outcome is **waiting / discovery_continues_next_run**,
not proof of production EAN writes. Discovery registrations and the checkpoint
were saved; there were no detail/product/price writes. All 25 unused detail
slots were refunded, daily usage is zero, and the next cursor is page 11.
Known records were not reset or replayed to manufacture write evidence.

The source/transport repair is proven and pushed to main. The remaining gate
is an actual new-product write verification; scheduling and Windows retirement
remain conditional on that gate. The Windows detail cron is retained. Existing
prices remain on their independent daily schedule.
