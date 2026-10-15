# Windows scraper inventory

The source repository contains **32 Windows workflow files** for **28 unique
shops**. The distinction matters because Bob's Vinyl, Everything Jazz, iMusic
and Platenzaak already have multiple Windows workflows.

The target layout is therefore:

- 28 independent catalog-price Actions;
- 28 independent EAN/detail Actions;
- 32 inactive, byte-for-byte Windows backups under
  `workflow-backups/windows/`.

The backup copies are deliberately outside `.github/workflows/`, so they are
not scheduled. A worker is only activated after its Ubuntu command has been
verified against the corresponding source workflow.
