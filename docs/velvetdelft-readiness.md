# Velvet Delft — preliminary read-only probe

Status: **research / NOT production ready**.

Entry: `python -m scripts.scrapers.velvetdelft_probe --genre prog`

The probe reads only the *first* page of one genre, checks robots.txt, extracts release IDs and URLs, and prints JSON. No database connection, import, workflow, cron, or publication. No claims of vinyl-only coverage, complete pagination, price, stock, or GTIN.

Before launch, verify actual genre URL slugs from the navigation; validate LP/7-inch/10-inch/12-inch filters and pagination using real HTML; ensure listing-first price and stock, discount handling, detail EAN/GTIN validation, deduplication, availability rules, proper USF staging, retries/rate limits and safeguards. A zero-row page MUST fail rather than delist existing stock. Do not activate writes or schedules until tests and sample quality report pass.

Unit tests: `python -m unittest tests.test_velvetdelft_probe`.
