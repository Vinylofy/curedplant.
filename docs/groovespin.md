# GrooveSpin

The Ubuntu workflow reads the public Dutch album sitemap, then uses structured
offers on each album page for prices and identifiers. Each accepted offer
belongs to an explicit new vinyl release. The CSV retains prices even when an
EAN is missing. The existing Curedplant importer publishes rows with a valid
EAN, an artist and a title. It retains the release link and reported stock
status. Offers that disappear from a crawl are left to the existing offer
lifecycle.

Scheduled collection runs four times per day on the default branch. Each run
reserves up to 250 album pages
against a shared 1,000-page daily ceiling in Europe/Amsterdam. The cursor
advances after processing and resumes at the next numeric album ID. The
worker circles back after reaching the end. There is a minimum two-second
request interval. HTTP 401, 403 or 429 stops the batch and subsequent write
batches for that local day.

A manual run defaults to a dry run of 20 albums. Set `write` to true for a
database-backed run with the existing `DATABASE_URL` secret. After a batch
imports offers, the worker records NL and BE delivery in the shop details.
Advertised starting rates and their sources are in
`config/groovespin-shop.json`. Checkout determines the actual fee.

At the initial probe there were 109,362 unique album pages, including albums
with no new vinyl offer. At full utilization this is roughly 110 days per
pass. Faster whole-catalogue price refresh requires a bulk source from the shop.
