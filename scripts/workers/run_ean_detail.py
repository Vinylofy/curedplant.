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
        "atthemovies": common + ["scripts.scrapers.atthemovies", "--max-pages", "1", "--detail-limit", str(limit), "--output", "output/atthemovies"],
        "bestkeptrecords": common + ["scripts.scrapers.bestkeptrecords", "--max-pages", "1", "--detail-limit", str(limit), "--output-dir", "output/bestkeptrecords"],
        "blackvinyl": common + ["scripts.scrapers.blackvinyl", "--detail-mode", "all", "--output", "output/blackvinyl.csv"],
        "getbackmusic": common + ["scripts.scrapers.getbackmusic", "--mode", "detail", "--max-pages", "1", "--detail-limit", str(limit), "--output-dir", "output/getbackmusic"],
        "rockinoutrecords": common + ["scripts.scrapers.rockinoutrecords", "--max-pages", "1", "--detail-limit", str(limit), "--output-dir", "output/rockinoutrecords"],
        "topnotch": common + ["scripts.scrapers.topnotch", "--max-pages", "1", "--detail-limit", str(limit), "--output-dir", "output/topnotch"],
        "vinyleers": common + ["scripts.scrapers.vinyleers", "--max-pages", "1", "--detail-limit", str(limit), "--output-dir", "output/vinyleers"],
        "vinylfreaks": common + ["scripts.scrapers.vinylfreaks", "--mode", "detail", "--max-pages", "1", "--detail-limit", str(limit), "--output-dir", "output/vinylfreaks"],
        "viprecords": common + ["scripts.scrapers.viprecords", "--mode", "detail", "--max-pages", "1", "--detail-limit", str(limit), "--output-dir", "output/viprecords"],
        "cdhal": common + ["scripts.scrapers.usf.jobs.run_cdhal_pipeline", "--skip-listing", "--run-detail", "--detail-limit", str(limit), "--skip-stage", "--skip-promote", "--skip-quarantine"],
        "colouredvinyl": common + ["scripts.scrapers.usf.jobs.run_colouredvinyl_pipeline", "--mode", "dry-run", "--steps", "detail", "--detail-limit", str(limit)],
        "dgmoutlet": common + ["scripts.scrapers.usf.jobs.run_dgmoutlet_pipeline", "--skip-discovery", "--skip-requeue", "--skip-stage", "--skip-promote", "--skip-quarantine", "--materialize-limit", str(limit)],
        "shop3345": common + ["scripts.scrapers.usf.jobs.detail_shop3345", "--limit", str(limit)],
        "variaworld": common + ["scripts.scrapers.usf.jobs.detail_variaworld", "--limit", str(limit)],
        "suburban": common + ["scripts.scrapers.suburban", "--mode", "detail", "--max-pages", "1", "--detail-limit", str(limit), "--output-dir", "output/suburban"],
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
    if args.write and args.worker in {"bobsvinyl", "everythingjazz", "imusic", "jpc", "myrecordstore", "northendhaarlem", "platenzaak", "soundshaarlem", "soundsvenlo", "cdhal", "colouredvinyl", "dgmoutlet", "shop3345"}:
        command.append("--write")
    print("[CUREDPLANT] ean-detail:", " ".join(command), flush=True)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
