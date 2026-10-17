"""Run one EAN/detail worker with an explicit, safe write switch."""

from __future__ import annotations

import argparse
import subprocess
import sys


def command_for(worker: str, limit: int) -> list[str]:
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
        "recordsonvinyl": common + ["scripts.scrapers.recordsonvinyl", "--master-csv", "data/raw/recordsonvinyl/recordsonvinyl_master.csv", "crawl", "--max-pages", "1", "--limit-products", str(limit)],
        "sounds": common + ["scripts.scrapers.usf.jobs.detail_sounds", "--limit", str(limit)],
        "shop3345": common + ["scripts.scrapers.usf.jobs.detail_shop3345", "--limit", str(limit)],
        "variaworld": common + ["scripts.scrapers.usf.jobs.detail_variaworld", "--limit", str(limit)],
        "suburban": common + ["scripts.workers.run_legacy_db", "--worker", "suburban", "--lane", "detail", "--limit", str(limit)],
    }
    try:
        return commands[worker]
    except KeyError as exc:
        raise SystemExit(f"Unsupported EAN/detail worker: {worker}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    command = command_for(args.worker, args.limit)
    if args.write and args.worker in {"atthemovies", "bestkeptrecords", "blackvinyl", "fiftiesstore", "getbackmusic", "rockinoutrecords", "topnotch", "vinyleers", "vinylfreaks", "viprecords", "bobsvinyl", "everythingjazz", "imusic", "jpc", "myrecordstore", "northendhaarlem", "platenzaak", "soundshaarlem", "soundsvenlo", "cdhal", "colouredvinyl", "dgmoutlet", "shop3345"}:
        command.append("--write")
    print("[CUREDPLANT] ean-detail:", " ".join(command), flush=True)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
