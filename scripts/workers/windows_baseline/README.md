# Windows source baseline for Linux comparison

These four Python files are unchanged copies from `Vinylofy/Vinylofy` commit
`c4b86b475c3af219b5f5dee77335c625af24605f`, the source of successful Windows runs
North End `39015584821` and Sounds Venlo `39029778437` on 17 October 2026.
`manifest.json` records their original paths and SHA-256 hashes; the pilot checks
these before import. Shared USF helper imports resolve in the current repository.

Use the read-only `scripts.workers.run_windows_baseline` harness, which calls
the original fetch and parse functions. Do not run these archived modules' native
`main()` functions: they belong to the older database pipelines and retain known
EAN defects. The harness compares their observed EANs with the repaired
product-scoped parsers and rejects disagreement. A correct checksum alone does
not establish that a barcode belongs to the current album.

The existing four manual workflows offer `source_version=current` (repaired Windows HTTP/browser profile and
product-scoped EAN checks) or `windows-baseline` (unchanged source comparison).
The EAN workflows default to `current`; price workflow defaults are unchanged. The baseline uses Ubuntu and Python 3.11, matching the
Windows Python minor version. Dependencies still come from the current
requirements; runtime versions are included in the artifact. This reproduces
the shop source code and its HTTP settings, not the Windows machine or network.

Baseline restrictions: no database credentials supplied, no writes accepted,
one to three listing pages (North End: first category only), at most 25 detail
records from the first listing page, one native fetch attempt, and 30/10 seconds
between North End/Sounds Venlo document requests. An ordinary browser fallback
is retained only where the original Venlo listing code uses it. A 429 stops
without that fallback. No new schedules or Windows deactivations are included.

Examples:

```sh
python -m scripts.workers.run_catalog_price --worker northendhaarlem --limit 1 --source-version windows-baseline
python -m scripts.workers.run_ean_detail --worker soundsvenlo --limit 5 --source-version windows-baseline
```

JSON evidence is saved under `output/windows-baseline/` and uploaded by the
Action, including source commit, reference Windows run, actual HTTP observations,
response hashes, listing prices, old/new EAN comparison, failures and runtime.
Green price results establish listing extraction only; they do not certify a
complete catalog, detail EAN matching or a production database write.
