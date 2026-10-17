"""Run one EAN/detail worker with an explicit, safe write switch."""

from __future__ import annotations

import argparse
import subprocess
import sys


def command_for(worker: str, limit: int, write: bool = False) -> list[str]:
    common = [sys.executable, "-u", "-m"]
    commands: dict[str, list[str]] = {
        "bobsvinyl": common + ["scripts.scrapers.usf.jobs.detail_bobsvinyl", "--limit", str(limit)],
        "everythingjazz": common + ["scripts.scrapers.usf.jobs.detail_everythingjazz", "--limit", str(limit)],
        "imusic": common + ["scripts.scrapers.usf.jobs.detail_imusic", "--limit", str(limit)],
        "jpc": common + ["scripts.scrapers.usf.jobs.detail_jpc", "--limit", str(limit)],
        "myrecordstore": common + ["scripts.scrapers.usf.jobs.detail_myrecordstore", "--limit", str(limit)],
        "northendhaarlem": common + ["scripts.scrapers.usf.jobs.detail_northendhaarlem", "--limit", str(limit)],
        "platenzaak": common + ["scripts.scrapers.usf.jobs.detail_platenzaak", "--limit", str(limit)],
        "soundshaarlem": common + ["scripts.scrapers.usf.jobs.detail_soundshaarlem", "--limit", str(limit)],
        "soundsvenlo": common + ["scripts.scrapers.usf.jobs.detail_soundsvenlo", "--limit", str(limit)],
        "fiftiesstore": common + ["scripts.scrapers.usf.jobs.promote_fiftiesstore", "--limit", str(limit)],
        "musiconvinyl": common + ["scripts.scrapers.usf.jobs.enrich_musiconvinyl_details", "--limit", str(limit)],
        "atthemovies": common + ["scripts.workers.run_legacy_db", "--worker", "atthemovies", "--lane", "detail", "--limit", str(limit)],
        "bestkeptrecords": common + ["scripts.workers.run_legacy_db", "--worker", "bestkeptrecords", "--lane", "detail", "--limit", str(limit)],
        "blackvinyl": common + ["scripts.workers.run_legacy_db", "--worker", "blackvinyl", "--lane", "detail", "--limit", str(limit)],
        "getbackmusic": common + ["scripts.workers.run_legacy_db", "--worker", "getbackmusic", "--lane", "detail", "--limit", str(limit)],
        "rockinoutrecords": common + ["scripts.workers.run_legacy_db", "--worker", "rockinoutrecords", "--lane", "detail", "--limit", str(limit)],
        "topnotch": common + ["scripts.workers.run_legacy_db", "--worker", "topnotch", "--lane", "detail", "--limit", str(limit)],
        "vinyleers": common + ["scripts.workers.run_legacy_db", "--worker", "vinyleers", "--lane", "detail", "--limit", str(limit)],
        "vinylfreaks": common + ["scripts.workers.run_legacy_db", "--worker", "vinylfreaks", "--lane", "detail", "--limit", str(limit)],
        "viprecords": common + ["scripts.workers.run_legacy_db", "--worker", "viprecords", "--lane", "detail", "--limit", str(limit)],
        "cdhal": common + ["scripts.scrapers.usf.jobs.run_cdhal_pipeline", "--skip-listing", "--run-detail", "--detail-limit", str(limit), "--skip-stage", "--skip-promote", "--skip-quarantine"],
        "colouredvinyl": common + ["scripts.scrapers.usf.jobs.run_colouredvinyl_pipeline", "--mode", "dry-run", "--steps", "detail", "--detail-limit", str(limit)],
        "dgmoutlet": common + ["scripts.scrapers.usf.jobs.run_dgmoutlet_pipeline", "--skip-discovery", "--skip-requeue", "--skip-stage", "--skip-promote", "--skip-quarantine", "--materialize-limit", str(limit)],
        "platomania": common + ["scripts.scrapers.platomania", "--mode", "both", "--output-dir", "data/raw/platomania", "--limit", str(limit)],
        "recordsonvinyl": common + ["scripts.scrapers.recordsonvinyl", "--master-csv", "data/raw/recordsonvinyl/recordsonvinyl_master.csv", "--out", "data/raw/recordsonvinyl/recordsonvinyl_products.csv", "crawl", "--max-pages", "1", "--limit-products", str(limit)],
        "sounds": common + ["scripts.scrapers.usf.jobs.detail_sounds", "--limit", str(limit)],
        "shop3345": common + ["scripts.scrapers.usf.jobs.detail_shop3345", "--limit", str(limit)],
        "variaworld": common + ["scripts.scrapers.usf.jobs.detail_variaworld", "--limit", str(limit)],
        "suburban": common + ["scripts.workers.run_legacy_db", "--worker", "suburban", "--lane", "detail", "--limit", str(limit)],
    }
    try:
        return commands[worker]
    except KeyError as exc:
        raise SystemExit(f"Unsupported EAN/detail worker: {worker}") from exc


def preflight_command(worker: str, limit: int, write: bool) -> list[str] | None:
    """Refresh a shop-specific link registry before detail enrichment.

    Detail workers intentionally consume the registry; they must not be run
    against stale URLs left by an old listing snapshot.  Preflight is only
    enabled for an explicit database-write run.  A dry-run therefore remains
    read-only and reports the existing queue instead of silently mutating it.
    """
    if not write:
        return None
    common = [sys.executable, "-u", "-m"]
    commands = {
        "everythingjazz": common + [
            "scripts.scrapers.usf.jobs.refresh_everythingjazz_listing_prices",
            "--max-pages", "1", "--max-products", str(limit), "--write",
        ],
        "fiftiesstore": common + [
            "scripts.scrapers.usf.jobs.refresh_fiftiesstore_listing_prices",
            "--max-products", str(limit), "--write",
        ],
        "myrecordstore": common + [
            "scripts.scrapers.usf.jobs.refresh_myrecordstore_listing_prices",
            "--max-pages", "1", "--write",
        ],
        "northendhaarlem": common + [
            "scripts.scrapers.usf.jobs.refresh_northendhaarlem_listing_prices",
            "--category-limit", "1", "--max-pages-per-category", "1", "--write",
        ],
        "soundshaarlem": common + [
            "scripts.scrapers.usf.jobs.refresh_soundshaarlem_listing_prices",
            "--seed-limit", "1", "--max-pages-per-seed", "1", "--write",
        ],
        "soundsvenlo": common + [
            "scripts.scrapers.usf.jobs.refresh_soundsvenlo_listing_prices",
            "--max-pages", "1", "--write",
        ],
        "shop3345": common + [
            "scripts.scrapers.usf.jobs.refresh_shop3345_listing_prices",
            "--max-pages", "1", "--write",
        ],
    }
    return commands.get(worker)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    preflight = preflight_command(args.worker, args.limit, args.write)
    if preflight:
        print("[CUREDPLANT] listing preflight:", " ".join(preflight), flush=True)
        preflight_result = subprocess.run(preflight, check=False)
        if preflight_result.returncode:
            return preflight_result.returncode
    command = command_for(args.worker, args.limit, args.write)
    if args.worker == "sounds" and not args.write:
        command.append("--dry-run")
    if args.write and args.worker in {"atthemovies", "bestkeptrecords", "blackvinyl", "fiftiesstore", "getbackmusic", "rockinoutrecords", "topnotch", "vinyleers", "vinylfreaks", "viprecords", "bobsvinyl", "everythingjazz", "imusic", "jpc", "myrecordstore", "northendhaarlem", "platenzaak", "soundshaarlem", "soundsvenlo", "cdhal", "colouredvinyl", "dgmoutlet", "shop3345"}:
        command.append("--write")
    print("[CUREDPLANT] ean-detail:", " ".join(command), flush=True)
    result = subprocess.run(command, check=False)
    if result.returncode:
        return result.returncode

    # These two CSV-native scrapers need their own importer checkpoint so the
    # pilot reports accepted/rejected EAN quality instead of only exiting 0.
    if args.worker in {"platomania", "recordsonvinyl"}:
        importer = "scripts.importers.import_platomania" if args.worker == "platomania" else "scripts.importers.import_recordsonvinyl"
        import_command = [sys.executable, "-u", "-m", importer]
        if not args.write:
            import_command.append("--dry-run")
        print("[CUREDPLANT] importer:", " ".join(import_command), flush=True)
        return subprocess.run(import_command, check=False).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
