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

All 28 price workers are being tested with `write=false` first. Existing three
price schedules are paused for this verification; EAN schedules are unchanged.
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

| Shop | Dry-run | Write verification | Price schedule | Windows price |
|---|---|---|---|---|
| atthemovies | pending | not started | paused | unchanged |
| bestkeptrecords | pending | not started | paused | unchanged |
| blackvinyl | pending | not started | paused | unchanged |
| bobsvinyl | pending | not started | paused | unchanged |
| cdhal | pending | not started | paused | unchanged |
| colouredvinyl | pending | not started | paused | unchanged |
| dgmoutlet | pending | not started | paused | unchanged |
| everythingjazz | pending | not started | paused | unchanged |
| fiftiesstore | pending | not started | paused | unchanged |
| getbackmusic | pending | not started | paused | unchanged |
| imusic | pending | not started | paused | unchanged |
| jpc | pending | not started | paused | unchanged |
| musiconvinyl | pending | not started | paused | unchanged |
| myrecordstore | pending | not started | paused | unchanged |
| northendhaarlem | pending | not started | paused | unchanged |
| platenzaak | pending | not started | paused | unchanged |
| platomania | pending | not started | paused | unchanged |
| recordsonvinyl | pending | not started | paused | unchanged |
| rockinoutrecords | pending | not started | paused | unchanged |
| sounds | pending | not started | paused | unchanged |
| soundshaarlem | pending | not started | paused | unchanged |
| soundsvenlo | pending | not started | paused | unchanged |
| suburban | pending | not started | paused | unchanged |
| topnotch | pending | not started | paused | unchanged |
| variaworld | pending | not started | paused | unchanged |
| vinyleers | pending | not started | paused | unchanged |
| vinylfreaks | pending | not started | paused | unchanged |
| viprecords | pending | not started | paused | unchanged |
