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
