"""Run one catalog-price worker with an explicit, safe write switch."""

from __future__ import annotations

import argparse
import subprocess
import sys


def command_for(worker: str, limit: int) -> list[str]:
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
        "atthemovies": common + ["scripts.scrapers.atthemovies", "--max-pages", str(limit), "--detail-limit", "0", "--output", "output/atthemovies"],
        "bestkeptrecords": common + ["scripts.scrapers.bestkeptrecords", "--max-pages", str(limit), "--detail-limit", "0", "--output-dir", "output/bestkeptrecords"],
        "blackvinyl": common + ["scripts.scrapers.blackvinyl", "--per-page", "50", "--detail-mode", "none", "--output", "output/blackvinyl.csv"],
        "getbackmusic": common + ["scripts.scrapers.getbackmusic", "--mode", "listing", "--max-pages", str(limit), "--output-dir", "output/getbackmusic"],
        "rockinoutrecords": common + ["scripts.scrapers.rockinoutrecords", "--max-pages", str(limit), "--detail-limit", "0", "--output-dir", "output/rockinoutrecords"],
        "topnotch": common + ["scripts.scrapers.topnotch", "--max-pages", str(limit), "--detail-limit", "0", "--output-dir", "output/topnotch"],
        "vinyleers": common + ["scripts.scrapers.vinyleers", "--max-pages", str(limit), "--detail-limit", "0", "--output-dir", "output/vinyleers"],
        "vinylfreaks": common + ["scripts.scrapers.vinylfreaks", "--mode", "listing", "--max-pages", str(limit), "--output-dir", "output/vinylfreaks"],
        "viprecords": common + ["scripts.scrapers.viprecords", "--mode", "listing", "--max-pages", str(limit), "--output-dir", "output/viprecords"],
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
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    command = command_for(args.worker, args.limit)
    if args.write and args.worker in {"bobsvinyl", "everythingjazz", "fiftiesstore", "musiconvinyl", "myrecordstore", "northendhaarlem", "platenzaak", "platomania", "recordsonvinyl", "sounds", "soundshaarlem", "soundsvenlo", "variaworld", "cdhal", "colouredvinyl", "dgmoutlet", "imusic", "jpc"}:
        command.append("--write")
    print("[CUREDPLANT] catalog-price:", " ".join(command), flush=True)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
