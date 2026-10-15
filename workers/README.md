# Curedplant scraper workers

The workers are deliberately split into two independent lanes:

- **catalog price**: listing/catalog requests and price synchronization only;
- **EAN/detail**: detail-page requests and EAN/detail enrichment only.

Both lanes default to a dry run. A database write requires the explicit
`write` input in Actions. The worker scripts use the same database schema as
Vinylofy and expect the repository secret `DATABASE_URL`.

The command mappings live in `scripts/workers/`. Add a new worker there only
after its command has passed the compile/CLI checks. The Windows counterpart
is not retired automatically: it can be disabled only after the corresponding
Curedplant worker has a successful green run with verified output.
