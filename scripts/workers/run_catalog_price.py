"""Run one catalog-price worker with an explicit, safe write switch."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys


IMUSIC_GENRES = "30:Country,44:Electronic,51:Folk,60:Gospel-Christian,66:Metal,73:Industrial,74:Instrumental,76:Jazz,94:Musical,98:New-Age,104:Pop,112:Reggae,115:Rock,128:Soundtrack,132:Spoken-Word,151:World-International,157:Easy-Listening,784:Klassiek,808:Kerstmis,2111:Schlager,2460:Hip-Hop-Rap,3018:K-pop,16415:Singer-songwriter,16619:Soul-RnB,16637:Indie,17888:Punk,33988:Downtempo,34057:Nu-Metal,34657:Eurodance,16:Blues"


def command_for(worker: str, limit: int, source_version: str = "current", write: bool = False) -> list[str]:
    if source_version == "windows-baseline":
        from scripts.workers.run_windows_baseline import command_for as baseline_command
        return baseline_command(worker, "price", limit)
    common = [sys.executable, "-u", "-m"]
    commands: dict[str, list[str]] = {
        "bobsvinyl": common + ["scripts.scrapers.usf.jobs.refresh_bobsvinyl_listing_prices", "--start-page", "1", "--max-pages", str(limit)],
        "everythingjazz": common + ["scripts.scrapers.usf.jobs.refresh_everythingjazz_listing_prices", "--start-page", "1", "--max-pages", str(limit)],
        "fiftiesstore": common + ["scripts.scrapers.usf.jobs.refresh_fiftiesstore_listing_prices", "--max-products", str(limit), "--vinyl-only", "--skip-delist-missing"],
        "musiconvinyl": common + ["scripts.scrapers.usf.jobs.refresh_musiconvinyl_prices_only", "--max-pages", str(limit), "--listing-limit", "250"],
        "myrecordstore": common + ["scripts.scrapers.usf.jobs.refresh_myrecordstore_listing_prices", "--max-pages", str(limit)],
        "northendhaarlem": common + ["scripts.scrapers.usf.jobs.refresh_northendhaarlem_listing_prices", "--max-pages-per-category", str(limit), "--delay-seconds", "30"] + (["--category-limit", "1"] if limit > 0 else []),
        "platenzaak": common + ["scripts.scrapers.usf.jobs.refresh_platenzaak_listing_prices", "--max-pages", str(limit)],
        "platomania": common + ["scripts.scrapers.usf.jobs.refresh_platomania_listing_prices", "--max-pages-per-seed", str(limit)],
        "recordsonvinyl": common + ["scripts.scrapers.usf.jobs.refresh_recordsonvinyl_listing_prices", "--max-pages", str(limit)],
        "sounds": common + ["scripts.scrapers.usf.jobs.refresh_sounds_listing_prices", "--max-pages", str(limit)],
        "soundshaarlem": common + ["scripts.scrapers.usf.jobs.refresh_soundshaarlem_listing_prices", "--max-pages-per-seed", str(limit)],
        "soundsvenlo": common + ["scripts.scrapers.usf.jobs.refresh_soundsvenlo_listing_prices", "--max-pages", str(limit), "--sleep", "10"],
        "variaworld": common + ["scripts.scrapers.usf.jobs.refresh_variaworld_listing_prices", "--max-pages", str(limit)],
        "atthemovies": common + ["scripts.workers.run_legacy_db", "--worker", "atthemovies", "--lane", "price", "--limit", str(limit)],
        "bestkeptrecords": common + ["scripts.workers.run_legacy_db", "--worker", "bestkeptrecords", "--lane", "price", "--limit", str(limit)],
        "blackvinyl": common + ["scripts.workers.run_legacy_db", "--worker", "blackvinyl", "--lane", "price", "--limit", str(limit)],
        "getbackmusic": common + ["scripts.workers.run_legacy_db", "--worker", "getbackmusic", "--lane", "price", "--limit", str(limit)],
        "rockinoutrecords": common + ["scripts.workers.run_legacy_db", "--worker", "rockinoutrecords", "--lane", "price", "--limit", str(limit)],
        "topnotch": common + ["scripts.workers.run_legacy_db", "--worker", "topnotch", "--lane", "price", "--limit", str(limit)],
        "vinyleers": common + ["scripts.workers.run_legacy_db", "--worker", "vinyleers", "--lane", "price", "--limit", str(limit)],
        "vinylfreaks": common + ["scripts.workers.run_legacy_db", "--worker", "vinylfreaks", "--lane", "price", "--limit", str(limit)],
        "viprecords": common + ["scripts.workers.run_legacy_db", "--worker", "viprecords", "--lane", "price", "--limit", str(limit)],
        "cdhal": common + ["scripts.scrapers.usf.jobs.refresh_cdhal_listing_prices", "--max-pages", str(limit)],
        "colouredvinyl": common + ["scripts.scrapers.usf.jobs.refresh_colouredvinyl_listing_prices", "--max-pages", str(limit)],
        "dgmoutlet": common + ["scripts.scrapers.usf.jobs.discover_dgmoutlet", "--max-pages", str(limit), "--delay", "0.5", "--listing-only"],
        "imusic": common + ["scripts.scrapers.usf.jobs.discover_imusic_genres", "--max-pages-per-genre", str(limit), "--delay", "4.0", "--genre-ids", IMUSIC_GENRES],
        "jpc": common + ["scripts.workers.jpc_price_source", "--limit", str(limit)],
        "suburban": common + ["scripts.scrapers.usf.jobs.refresh_suburban_listing_prices", "--max-pages", str(limit)],
    }
    try:
        return commands[worker]
    except KeyError as exc:
        raise SystemExit(f"Unsupported catalog-price worker: {worker}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--approved-source-dir")
    parser.add_argument("--approved-source-run")
    parser.add_argument("--source-version", choices=("current", "windows-baseline"), default="current")
    args = parser.parse_args()
    if bool(args.approved_source_dir) != bool(args.approved_source_run):
        parser.error("Approved source directory and run ID are both required")
    if args.approved_source_run and args.source_version != "current":
        parser.error("Source evidence reuse is only allowed for the current source")
    if args.limit < 0:
        parser.error("--limit must be >= 0; 0 follows native pagination stop conditions")
    if args.source_version == "windows-baseline":
        if args.write:
            parser.error("Windows baseline is read-only; write=true is not allowed")
        return subprocess.run(command_for(args.worker, args.limit, args.source_version), check=False).returncode

    from scripts.workers.price_evidence import assess
    from scripts.workers.price_database import update_existing
    started = datetime.now(timezone.utc)
    directory = Path("output/price-verification") / args.worker
    directory.mkdir(parents=True, exist_ok=True)
    evidence = directory / "listing-records.jsonl"
    evidence.write_text("")
    if args.approved_source_run:
        from scripts.workers.approved_price_source import load_approved_source
        records, started = load_approved_source(args.approved_source_dir, args.worker, args.limit, args.approved_source_run, require_green=args.write)
        evidence.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
        source_returncode = 0
        print(f"[CUREDPLANT] revalidate source run {args.approved_source_run}; no second catalogue fetch", flush=True)
    else:
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", DATABASE_URL="", CUREDPLANT_PRICE_EVIDENCE=str(evidence.resolve()),
                   PGOPTIONS="-c default_transaction_read_only=on")
        # Native collection never receives a DB credential or a write flag.
        command = command_for(args.worker, args.limit, args.source_version, write=True)
        if args.worker == "myrecordstore" and args.limit == 0:
            from scripts.workers.myrecordstore_targets import registered_offers
            targets = directory / "existing-offers.json"
            targets.write_text(json.dumps(registered_offers()))
            command += ["--existing-offers-file", str(targets.resolve())]
        print("[CUREDPLANT] native listing (database write=false):", " ".join(command), flush=True)
        source_returncode = subprocess.run(command, check=False, env=env).returncode
        records = [json.loads(line) for line in evidence.read_text().splitlines() if line.strip()]
    identity_review = None
    if args.worker == "variaworld" and source_returncode == 0 and not args.approved_source_run:
        import psycopg
        from scripts.workers.variaworld_identity import enrich_identities, fallback_matches
        from psycopg.rows import dict_row
        with psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None, row_factory=dict_row) as conn:
            conn.execute('set transaction read only')
            registered = conn.execute("""select pr.product_id,pr.product_url,p.ean,p.gtin_normalized
                from public.prices pr join public.shops sh on sh.id=pr.shop_id
                join public.products p on p.id=pr.product_id where sh.domain='variaworld.nl'""").fetchall()
            known_urls = [row['product_url'] for row in registered]
        identity_review = enrich_identities(records, known_urls,
            budget=int(os.environ.get('VARIAWORLD_IDENTITY_BUDGET', '200')))
        # The enriched evidence is the exact evidence reviewed by the writer.
        evidence.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in records))
    rows, summary = assess(records)
    if identity_review is not None:
        replacements = fallback_matches(rows, registered)
        identity_review['replacement_matches'] = len(replacements)
        identity_review['replacement_samples'] = [
            {'product_id': key, 'url': row['source_url'], 'price': row['price']}
            for key, row in list(replacements.items())[:5]]
        summary["identity_review"] = identity_review
    summary.update(worker=args.worker, write=args.write, limit=args.limit,
                   started_at=started.isoformat(), source_returncode=source_returncode,
                   approved_source_run=args.approved_source_run,
                   run_id=os.environ.get("GITHUB_RUN_ID"), database_writes=0)
    if source_returncode:
        summary["status"] = "red"
        summary["errors"].append({"reason": "native_source_failed", "returncode": source_returncode})
    if args.write and summary["status"] == "green":
        try:
            summary["database_writes"] = None  # A failed post-commit check must not falsely claim zero writes.
            stats = update_existing(args.worker, rows, started)
            summary["database"] = stats
            summary["database_writes"] = stats["updated"]
        except Exception as exc:
            summary["status"] = "red"
            summary["errors"].append({"reason": "database_verification_failed", "error": str(exc)})
    (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n")
    (directory / "validated-prices.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str) + "\n")
    print("[PRICE-VERIFICATION]", json.dumps({k:v for k,v in summary.items() if k != "samples"}, default=str), flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(f"### {args.worker} | Price | write={args.write}: {summary['status']}\n\n"
                         f"Products with valid prices: {len(rows)}; distinct prices: {summary['distinct_prices']}; "
                         f"database rows updated: {summary['database_writes']}.\n\n"
                         + "\n".join(f"- {error}" for error in summary["errors"]) + "\n")
    return 0 if summary["status"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
