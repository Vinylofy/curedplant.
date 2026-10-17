"""Run one catalog-price worker with an explicit, safe write switch."""

from __future__ import annotations

import argparse
import subprocess
import sys


def command_for(worker: str, limit: int, source_version: str = "current") -> list[str]:
    if source_version == "windows-baseline":
        from scripts.workers.run_windows_baseline import command_for as baseline_command
        return baseline_command(worker, "price", limit)
    common = [sys.executable, "-u", "-m"]
    commands: dict[str, list[str]] = {
        "bobsvinyl": common + ["scripts.scrapers.usf.jobs.refresh_bobsvinyl_listing_prices", "--start-page", "1", "--max-pages", str(limit)],
        "everythingjazz": common + ["scripts.scrapers.usf.jobs.refresh_everythingjazz_listing_prices", "--start-page", "1", "--max-pages", str(limit)],
        "fiftiesstore": common + ["scripts.scrapers.usf.jobs.refresh_fiftiesstore_listing_prices", "--max-products", str(limit)],
        "musiconvinyl": common + ["scripts.scrapers.usf.jobs.refresh_musiconvinyl_prices_only", "--max-pages", str(limit), "--listing-limit", str(limit * 25)],
        "myrecordstore": common + ["scripts.scrapers.usf.jobs.refresh_myrecordstore_listing_prices", "--max-pages", str(limit)],
        "northendhaarlem": common + ["scripts.scrapers.usf.jobs.refresh_northendhaarlem_listing_prices", "--max-pages-per-category", str(limit)],
        "platenzaak": common + ["scripts.scrapers.usf.jobs.refresh_platenzaak_listing_prices", "--max-pages", str(limit)],
        "platomania": common + ["scripts.scrapers.usf.jobs.refresh_platomania_listing_prices", "--max-pages-per-seed", str(limit)],
        "recordsonvinyl": common + ["scripts.scrapers.usf.jobs.refresh_recordsonvinyl_listing_prices", "--max-pages", str(limit)],
        "sounds": common + ["scripts.scrapers.usf.jobs.refresh_sounds_listing_prices", "--max-pages", str(limit)],
        "soundshaarlem": common + ["scripts.scrapers.usf.jobs.refresh_soundshaarlem_listing_prices", "--max-pages-per-seed", str(limit)],
        "soundsvenlo": common + ["scripts.scrapers.usf.jobs.refresh_soundsvenlo_listing_prices", "--max-pages", str(limit)],
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
        "cdhal": common + ["scripts.scrapers.usf.jobs.run_cdhal_pipeline", "--listing-max-pages", str(limit), "--skip-stage", "--skip-promote", "--skip-quarantine"],
        "colouredvinyl": common + ["scripts.scrapers.usf.jobs.run_colouredvinyl_pipeline", "--mode", "dry-run", "--steps", "listing"],
        "dgmoutlet": common + ["scripts.scrapers.usf.jobs.run_dgmoutlet_pipeline", "--discovery-max-pages", str(limit), "--skip-requeue", "--skip-stage", "--skip-promote", "--skip-quarantine"],
        "imusic": common + ["scripts.scrapers.usf.jobs.sync_imusic_listing_prices", "--limit", str(limit * 500)],
        "jpc": common + ["scripts.scrapers.usf.jobs.sync_jpc_listing_prices", "--limit", str(limit * 500)],
        "suburban": common + ["scripts.scrapers.suburban", "--mode", "listing", "--max-pages", str(limit), "--output-dir", "output/suburban"],
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
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    if args.source_version == "windows-baseline" and args.write:
        parser.error("Windows baseline is read-only; write=true is not allowed")
    command = command_for(args.worker, args.limit, args.source_version)
    if args.write and args.worker in {"atthemovies", "bestkeptrecords", "blackvinyl", "getbackmusic", "rockinoutrecords", "topnotch", "vinyleers", "vinylfreaks", "viprecords", "bobsvinyl", "everythingjazz", "fiftiesstore", "musiconvinyl", "myrecordstore", "northendhaarlem", "platenzaak", "platomania", "recordsonvinyl", "sounds", "soundshaarlem", "soundsvenlo", "variaworld", "cdhal", "colouredvinyl", "dgmoutlet", "imusic", "jpc"}:
        command.append("--write")
    print("[CUREDPLANT] catalog-price:", " ".join(command), flush=True)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
