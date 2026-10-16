# Database-write audit

The write boundary is now explicit for the migrated workers:

- USF workers use their existing database-aware jobs and accept `--write`.
- Legacy listing/detail shops are routed through
  `scripts/workers/run_legacy_db.py`. That runner first creates the normal
  scraper checkpoint. The catalog-price lane updates existing
  `public.prices` rows by shop/product URL and intentionally does not require
  an EAN; the detail lane invokes the shop's registered importer. With
  `write=false` both lanes are dry-run; with `write=true` they write through
  `DATABASE_URL`.
- At The Movies is included in both lanes and uses the same registered
  importer, so its price and detail Actions no longer stop at CSV output.

Every Action remains manual-only during the pilot. A write run must have the
repository secret `DATABASE_URL`; a dry-run does not need it.
