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
        "fiftiesstore": common + ["scripts.scrapers.usf.jobs.refresh_fiftiesstore_listing_prices", "--max-products", str(limit)],
        "musiconvinyl": common + ["scripts.scrapers.usf.jobs.refresh_musiconvinyl_prices_only", "--max-pages", str(limit), "--listing-limit", "250"],
        "myrecordstore": common + ["scripts.scrapers.usf.jobs.refresh_myrecordstore_listing_prices", "--max-pages", str(limit)],
        "northendhaarlem": common + ["scripts.scrapers.usf.jobs.refresh_northendhaarlem_listing_prices", "--max-pages-per-category", str(limit), "--delay-seconds", "30"],
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
        "dgmoutlet": common + ["scripts.scrapers.usf.jobs.discover_dgmoutlet", "--max-pages", str(limit), "--delay", "0.5"],
        "imusic": common + ["scripts.scrapers.usf.jobs.discover_imusic_genres", "--max-pages-per-genre", str(limit), "--delay", "4.0", "--genre-ids", IMUSIC_GENRES],
        "jpc": common + ["scripts.scrapers.usf.jobs.discover_jpc_vinyl", "--max-pages-per-route", str(limit), "--include-route-index", "--pagination-fallback", "ff", "--delay", "2.0", "--availability-filter", "none"],
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
    parser.add_argument("--source-version", choices=("current", "windows-baseline"), default="current")
    args = parser.parse_args()
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
    env = dict(os.environ, DATABASE_URL="", CUREDPLANT_PRICE_EVIDENCE=str(evidence.resolve()),
               PGOPTIONS="-c default_transaction_read_only=on")
    # The native source always runs without --write, including in the write
    # phase. Only the verified price-only boundary below may mutate the DB.
    command = command_for(args.worker, args.limit, args.source_version, write=True)
    print("[CUREDPLANT] native listing (database write=false):", " ".join(command), flush=True)
    result = subprocess.run(command, check=False, env=env)
    records = [json.loads(line) for line in evidence.read_text().splitlines() if line.strip()]
    rows, summary = assess(records)
    summary.update(worker=args.worker, write=args.write, limit=args.limit,
                   started_at=started.isoformat(), source_returncode=result.returncode,
                   run_id=os.environ.get("GITHUB_RUN_ID"), database_writes=0)
    if result.returncode:
        summary["status"] = "red"
        summary["errors"].append({"reason": "native_source_failed", "returncode": result.returncode})
    if args.write and summary["status"] == "green":
        try:
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
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write(f"### {args.worker} | Price | write={args.write}: {summary['status']}\n\n"
                         f"Products with valid prices: {len(rows)}; distinct prices: {summary['distinct_prices']}; "
                         f"database rows updated: {summary['database_writes']}.\n\n"
                         + "\n".join(f"- {error}" for error in summary["errors"]) + "\n")
    return 0 if summary["status"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
