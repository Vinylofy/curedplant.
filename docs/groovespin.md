# GrooveSpin

The worker reads the public Dutch album sitemap for discovery and structured
offers on each album page for EAN enrichment. Only explicitly new vinyl offers
are written. A release provides its own EAN, price and availability. The CSV
retains prices when the EAN is missing. The existing Curedplant importer
accepts records with a valid identifier, an artist and a title.

## EAN enrichment

Four runs can reserve 250 album pages each against a 1,000-page ceiling per
Europe/Amsterdam calendar day. A page may yield zero or multiple EANs, so the
workflow reports valid unique GTINs separately. The cursor advances after
processing and resumes at the next numeric album ID. Requests are sequential,
at least two seconds apart. HTTP 401, 403 or 429 stops the batch and future
write batches for the day.

GitHub-hosted Ubuntu returned HTTP 403 on the public sitemap. Pull requests
therefore run offline tests on hosted Ubuntu. The live workflow requires
`GROOVESPIN_APPROVED_RUNNER` to identify a self-hosted Ubuntu runner with
approved shop access. Manual runs default to a read-only 20-album pilot. Only
enable scheduled production collection after a successful pilot from the
approved runner.

## Daily full price refresh

Prices observed during an EAN batch cover that batch only. The public sitemap
contained 109,362 unique album pages at the pilot, so this route cannot refresh
the entire catalogue daily. A daily round needs a complete new-vinyl EUR feed
or a partner API that supports full catalogue enumeration. The shop documents
keyed UCP search and lookup, but full enumeration has not been demonstrated.

## Registration

After a successful write batch, the existing importer sets the shop country
to CZ. The worker verifies active offers and both destinations before enabling
an existing inactive shop. It records the published pickup-point rate, from
EUR 6.76 for NL and BE, with the source and observation date. Final shipping
charges vary at checkout. See `config/groovespin-shop.json` for sources.
