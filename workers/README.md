# Curedplant scraper workers

The workers are deliberately split into two independent lanes:

- **catalog price**: listing/catalog requests and price synchronization only;
- **EAN/detail**: detail-page requests and EAN/detail enrichment only.

Manual runs default to a dry run. The 26 approved EAN workflows also run
daily with writes enabled, up to 100 new product details per shop and day.
Manual database writes require the explicit `write` input in Actions. The worker scripts use the same database schema as
Vinylofy and expect the repository secret `DATABASE_URL`.

The command mappings live in `scripts/workers/`. Add a new worker there only
after its command has passed the compile/CLI checks. The Windows counterpart
is not retired automatically: it can be disabled only after the corresponding
Curedplant worker has a successful green run with verified output.

Daily EAN orchestration lives in `scripts/workers/run_daily_ean.py`; catalogue
cursors and daily budgets persist on branch `automation/ean-progress`.
The per-shop database queue excludes completed detail records. EAN writes
contain metadata/product identity only, never prices or stock. See the
[central EAN status](../docs/ean-quality-status.md) for schedules and evidence.

Local validation: `python -m pip install -r requirements-dev.txt` followed by
`python -m unittest discover -s tests -v`. Optional SQL integration tests require
`EAN_TEST_DATABASE_URL` pointing to a disposable loopback Postgres; never an
application database. They create and drop their own public queue tables.
