# Bol NL cover discovery — activation remains disabled

Implementation/review date: 30 October 2026. This is candidate discovery with
mandatory quarantine. It does not publish, download, proxy, convert or host images.
Setting the publication flag to true deliberately fails configuration validation.

## Existing architecture: confirmed by repository inspection

Public `Vinylofy/curedplant.` baseline: `a7334b0246b4635d09346d90c66048b2dd5e77a9`.

* `scripts/importers/bol_api_review.py` already authenticates against the official
  Marketing Catalog API using `BOL_API_CLIENT_ID` / `BOL_API_CLIENT_SECRET`.
  It supplies bounded HTTP reads, a 30-second timeout, sanitized errors and
  redirect refusal. Its authentication and HTTP implementation are reused.
* `scripts/importers/bol_api_prices.py` already does exact GTIN matching and NL
  lookups. Its price publisher is intentionally not imported by this worker.
* `scripts/importers/common.py::strict_normalize_gtin` is the shared check-digit
  authority. Cover input additionally requires an intact digit-only barcode.
* The existing feed integration is separate. No feed download is needed here.
* `cover-publish.yml`, `cover-candidate-refresh.yml` and `cover-backfill.yml`
  are gated on `COVER_PIPELINE_ENABLED`, use Ubuntu and concurrency group
  `vinylofy-cover-pipeline`, and check out private `Vinylofy/Vinylofy` source.
  Their current flag values and deployed secret values were not accessible.
  None of these workflows has been disabled or changed.

Private `Vinylofy/Vinylofy/main` was inspected read-only through GitHub:

* `cover_candidate_refresh.py` writes `public.product_cover_candidates` and calls
  `queue_cover_for_products`; it preserves rejected candidate status.
* `cover_worker.py` is the centralized publisher. Normal candidate statuses are
  `pending`/`published`, retry-failed additionally allows `failed`. It downloads
  external images and prepares local Storage images. A normal Bol candidate
  would therefore violate the current image rights boundary.
* With no usable candidates the worker ends with queue status `review` and
  error `no_candidates`. This exact terminal evidence gates Bol discovery.
* `cover_common.py` owns ranking and Storage preparation. Shop source priorities,
  canonical EAN Storage paths, MusicBrainz metadata and publisher code are unchanged.
* `cover_backfill.py` orchestrates the existing refresh/publisher. Its pipeline
  is not duplicated or invoked by the new worker.
* Candidate/queue contracts were checked against migrations
  `20260404113000_add_cover_pipeline_v1.sql` and
  `20260805123000_finalize_central_cover_pipeline.sql`, plus current worker code.
  No live database schema has been claimed as verified.

## Integration and safety

The additive migration changes only the existing queue and candidate tables.
There is no second cover database, queue table, product insertion or metadata
publication path. Existing queue status, priority, claims and errors stay intact.

Selection requires an existing terminal `no_candidates` queue row, no product
cover URL, source URL or Storage path, no blocked product, and no non-Bol
candidate that has not been rejected. Queueless products and products still
awaiting normal sources are deliberately excluded. Configure the existing
pipeline to attempt those sources promptly; this worker cannot establish their
exhaustion independently.

One queue row is locked with `FOR UPDATE SKIP LOCKED` per lookup transaction.
The evidence/checkpoint commits per product; crash recovery repeats only
uncommitted work. Private queue claims must acquire the same queue row lock.
The workflow also shares the existing public cover concurrency group; GitHub
concurrency groups alone do not coordinate across repositories.

Successful exact identity + variant checks register one candidate per product
with source `bol_affiliate`, rank zero, `candidate_status=rejected`, no executable
`image_url`/`product_url`, and external URL/product reference in `bol_evidence`.
This is a rights rejection, not a claim that the technical match failed.
A database constraint prevents promotion, selection or adding an executable URL.
The existing publisher's normal/retry paths cannot use it. Existing rejected
rows remain rejected. A future publication implementation requires a separate
review; flipping a flag cannot bypass this protection.

The API request is `/marketing/catalog/v1/products/{ean}` with `country-code=NL`,
`include-specifications=true`, `include-image=true`, and `Accept-Language: nl`.
`specificationGroups[].specifications[]` supplies format/variant evidence;
`image` is the documented main image. Unknown/conflicting formats, CD/LP conflicts,
missing images and variants without corroborating canonical evidence are skipped.
No title similarity is used to establish product identity. This conservative
first version can reject valid special editions rather than guess.

Positive evidence is cached 30 days; negative evidence 7 days, in the same queue.
API failures use a bounded exponential cooldown (1–24 hours); the six-hour
schedule may make the actual retry later. At most three transient attempts use
2/4-second backoff with request starts at least four seconds apart. HTTP 500,
401/403 and 429 end the request without blind retry. Any final API failure stops
the run. For 429 the shared HTTP helper does not expose Retry-After, so no
in-run retry is made; a later scheduled run retries after the durable cooldown.

Half the batch is reserved for new queue rows (first queued in the last seven
days), half for historical rows. Within each lane untried/oldest-checked rows
come first. The queue timestamp is the verified available proxy for new titles;
this does not claim to measure product creation time. Every run selects newly
arriving rows, with no completed catalogue cursor that can hide future arrivals.
Default capacity is 200 new and 200 historical attempts/day before failures.
The 24-hour goal depends on upstream completion, arrival volume and scheduler
delays; it is not a guaranteed SLA. Monitor `new_unchecked` before scaling.

## Rights: publication blocked

Reviewed official sources:

* [Affiliate terms](https://affiliate.bol.com/nl/algemene-voorwaarden/), currently
  dated 26 February 2026: article 3.2 requires retaining the original hosting URL
  and unmodified content; 3.4 requires nearby music content attribution; 3.5
  limits use to the affiliate programme; 3.17 requires removal on request.
* [Official FAQ](https://affiliate.bol.com/nl/veelgestelde-vragen/) describes
  linking/embedding images as the intended mechanism.
* [Marketing API specification](https://api.bol.com/marketing/docs/api-reference/catalog-api-v1.html)
  defines the lookup schema and explicitly says not to automatically retry 500.
* [Rate limits](https://api.bol.com/marketing/docs/catalog-api/ratelimits.html)
  recommends caching, monitoring and stopping on 429.

These sources do not unambiguously authorize a Bol image as a general Vinylofy
cover beside competing record shops. Obtain written clarification for that
specific use, including attribution, cache retention, original-URL display and
any proposed Storage copying/conversion. The current local Storage publisher
cannot meet an original-URL-only permission. No rights approval was inferred.

## Configuration and activation

See `config/bol-cover.env.example`.

| Setting | Location | Default / purpose |
| --- | --- | --- |
| `BOL_COVER_FALLBACK_ENABLED` | Repository variable | `false`; permits API discovery |
| `BOL_COVER_PUBLICATION_ENABLED` | Repository variable | `false`; true is blocked |
| `BOL_COVER_BATCH_SIZE` | Repository variable | `100`; valid range 1–100 |
| `BOL_API_CLIENT_ID` | Existing GitHub Secret | Existing official API identity |
| `BOL_API_CLIENT_SECRET` | Existing GitHub Secret | Existing API secret |
| `BOL_COVER_DATABASE_URL` | New GitHub Secret | Dedicated restricted direct Postgres login |

Frequency is configurable in the workflow's cron (initially `23 */6 * * *`, UTC).
No end date is encoded. GitHub's normal schedule availability/inactivity rules
still apply. Manual dispatch defaults to a no-write dry-run. Scheduled runs
persist quarantined evidence only once discovery is explicitly enabled.

1. Run the local PostgreSQL integration test against a disposable test server,
   then review the migration against the actual shared database schema and RLS.
2. An administrator explicitly applies the migration; the workflow never runs
   migrations or provisions credentials. It is transactional and repeatable.
3. Provision a separate LOGIN with SSL required and membership only in the
   NOLOGIN role `bol_cover_worker`. Do not grant it product/table/Storage writes,
   owner rights, `service_role`, `anon`, `authenticated` or privileged memberships.
   The migration grants only three bounded discovery function entry points.
   Check inherited/default privileges and existing table exposure before use.
4. Save its DSN as `BOL_COVER_DATABASE_URL`; reuse the existing Bol secrets.
   Neither Supabase service-role secrets nor private-repository read tokens are
   needed. Missing credentials/contracts stop before a lookup/write.
5. Start with batch size 5 and discovery enabled, publication disabled. Dispatch
   `write=false`; this makes API calls but zero database writes/claims/checkpoints.
6. Review technical counts and locally inspect evidence under authorized DB
   access. Then dispatch a small `write=true` candidate-only pilot and verify
   quarantine, uniqueness, cover preservation and queue state before scheduling.
7. Enable the normal 100-row cadence only after the pilot. Do not enable the three
   existing cover workflows simply to run this discovery worker. Do not remove
   them until any proposed replacement has its own evidence and approval.

Disable discovery to stop. The rollback revokes discovery execution while
preserving evidence and the quarantine constraint.

For removal, disable discovery and wait for active runs, count the exact target,
then run this as an administrator with a bound product UUID in one transaction:

```sql
begin;
select product_id from public.product_cover_queue where product_id = :product_id for update;
delete from public.product_cover_candidates
where product_id = :product_id and source_type = 'bol_affiliate';
update public.product_cover_queue
set bol_result = null, bol_next_attempt_at = 'infinity'
where product_id = :product_id;
commit;
```

The infinity tombstone prevents recreation. No Storage removal is necessary.

## Tests and actual verification

On 30 October 2026, local Python regression run: **72 tests, 63 passed, 9 skipped**.
This includes 23 new fallback unit/contract tests, existing Bol API/price/feed
tests, and optional database tests. The skipped tests need local PostgreSQL.
SQL syntax parsed successfully with pglast (19 statements, 7 PL/pgSQL blocks).
Parsing does not establish live schema compatibility or concurrency behavior.

The isolated PostgreSQL integration test is supplied in
`tests/test_bol_cover_postgres.py`; it creates a randomly named disposable
database and refuses non-local hosts. It tests repeated migration, concurrent
claims, durable checkpoints, uniqueness, quarantine, privileges and removal.
It has not run in this session: PostgreSQL is not installed/configured locally.

Local regression command (UTF-8 and tests directory on Python path are required
by existing feed tests on Windows):

```text
python -X utf8 -m unittest discover -s tests -p "test_bol_*.py"
```

For SQL integration set `BOL_COVER_TEST_ADMIN_DSN` to a localhost administrator
DSN and run `python -m unittest tests.test_bol_cover_postgres`. The fixture is
the minimal verified cover contract, not a copy of the production database.

The pre-existing private local checkout's repository contract suite ran 24
tests: 23 passed, one failed in `test_new_releases_use_central_cover_contract`
because it expects an exact `freshShopCount < 2` source string. No private file
was changed to address this unrelated baseline failure. Existing private
pipeline behavior is otherwise assessed from inspected source, not a live run.

No production DB/Storage writes, workflow dispatches or live Bol lookups were
performed. API credentials and both database DSNs were absent from this session.
No live dry-run or rights approval is claimed. The disabled CLI path has also
been exercised locally with all counters zero.

## Reporting and costs

Each executed worker emits only count summaries to stdout, the Actions summary
and a seven-day artifact. Counts distinguish technical accepted matches,
newly registered quarantined rows and published covers (always zero).
`database_writes` counts committed product evidence transactions, not SQL row
updates. Covered products are excluded in SQL; `skipped_existing` counts races
detected after selection. Backlog counts report eligible/new/historical unchecked
items. No raw API responses, commercial price data, titles, EANs, image URLs or
credentials are exported to public logs/artifacts.

[GitHub's current billing policy](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
makes standard GitHub-hosted runners free for public repositories. Estimated
nominal runtime is approximately 7–10 minutes per full 100-row run, 4 runs/day,
840–1200 runner minutes/30 days, with a hard 20-minute job limit. This is an
unmeasured estimate including setup; timeouts/retries can extend it. Runner
compute cost should be $0 while that policy and repository visibility hold.
Small summary artifact storage and Supabase/database/API usage remain subject
to their own quotas; no additional image Storage/egress is introduced.
