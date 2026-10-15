# Vinylofy → Curedplant migration

Source repository: `Vinylofy/Vinylofy`
Target repository: `Vinylofy/curedplant.`

The Ubuntu scraper source tree is copied into `scripts/scrapers/`. The new
Actions lanes are intentionally separate:

| lane | workflow | purpose | default |
|---|---|---|---|
| catalog price | `curedplant-catalog-price.yml` | listing/catalog prices | dry-run |
| EAN/detail | `curedplant-ean-detail.yml` | detail pages and EAN enrichment | dry-run |

Each workflow has a manual worker selector and a scheduled worker matrix. The
database write flag is explicit; schedules are configured to write because
these are the production Ubuntu replacements, while manual runs default to a
dry-run for verification.

To prevent duplicate writes while the old Vinylofy schedules are still live,
scheduled jobs are guarded by the repository variable
`CUREDPLANT_SCHEDULE_ENABLED`. Leave it unset during the pilot. After a worker
has passed its manual dry-run and one green write run, enable the variable and
then retire only that worker's old Windows/Ubuntu counterpart.

Windows counterparts in Vinylofy remain enabled during migration. Retire one
only after the same worker has a green Curedplant run and its output has been
checked. This prevents a failed migration from creating a data gap.

The repository must have these Actions secrets before a write run:

- `DATABASE_URL`

No secret values are copied between repositories.
