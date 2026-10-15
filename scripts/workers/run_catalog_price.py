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
    if args.write:
        command.append("--write")
    print("[CUREDPLANT] catalog-price:", " ".join(command), flush=True)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
