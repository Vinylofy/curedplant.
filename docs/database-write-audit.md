# Database-write audit

The write boundary is now explicit for the migrated workers:

- USF workers use their existing database-aware jobs and accept `--write`.
- Legacy listing/detail shops are routed through
  `scripts/workers/run_legacy_db.py`. That runner first creates the normal
  scraper checkpoint and then invokes the shop's registered importer. With
  `write=false` the importer is dry-run; with `write=true` it writes through
  `DATABASE_URL`.
- At The Movies is included in both lanes and uses the same registered
  importer, so its price and detail Actions no longer stop at CSV output.

Every Action remains manual-only during the pilot. A write run must have the
repository secret `DATABASE_URL`; a dry-run does not need it.
