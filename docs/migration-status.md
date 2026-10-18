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
with committed database price verification may enable its two-day schedule
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
| jpc | [in_progress](https://github.com/Vinylofy/curedplant./actions/runs/39111222968) | not started | off; pending verification | unchanged |
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
