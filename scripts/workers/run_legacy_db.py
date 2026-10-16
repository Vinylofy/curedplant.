"""Run legacy listing/detail scrapers and their registered DB importer.

The scraper still produces its normal CSV checkpoint, while the importer is
the only component allowed to write to the shared database.  This keeps a
manual dry-run safe and makes the write boundary explicit.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


PROFILES = {
    "atthemovies": ("scripts.scrapers.atthemovies", "scripts.importers.import_atthemovies", "single"),
    "bestkeptrecords": ("scripts.scrapers.bestkeptrecords", "scripts.importers.import_bestkeptrecords", "legacy"),
    "blackvinyl": ("scripts.scrapers.blackvinyl", "scripts.importers.import_blackvinyl", "blackvinyl"),
    "getbackmusic": ("scripts.scrapers.getbackmusic", "scripts.importers.import_getbackmusic", "mode"),
    "grooverecords": ("scripts.scrapers.grooverecords", "scripts.importers.import_grooverecords", "mode"),
    "rockinoutrecords": ("scripts.scrapers.rockinoutrecords", "scripts.importers.import_rockinoutrecords", "legacy"),
    "suburban": ("scripts.scrapers.suburban", "scripts.importers.import_suburban", "mode"),
    "topnotch": ("scripts.scrapers.topnotch", "scripts.importers.import_topnotch", "legacy"),
    "vinyleers": ("scripts.scrapers.vinyleers", "scripts.importers.import_vinyleers", "legacy"),
    "vinylfreaks": ("scripts.scrapers.vinylfreaks", "scripts.importers.import_vinylfreaks", "mode"),
    "viprecords": ("scripts.scrapers.viprecords", "scripts.importers.import_viprecords", "mode"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=sorted(PROFILES), required=True)
    parser.add_argument("--lane", choices=("price", "detail"), required=True)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    scraper, importer, style = PROFILES[args.worker]
    if args.limit < 1:
        parser.error("--limit must be >= 1")

    detail_limit = str(args.limit if args.lane == "detail" else 0)
    if style == "mode":
        scraper_args = ["--mode", "detail" if args.lane == "detail" else "listing", "--max-pages", "1" if args.lane == "detail" else str(args.limit), "--detail-limit", detail_limit]
    elif style == "blackvinyl":
        scraper_args = ["--detail-mode", "all" if args.lane == "detail" else "none", "--output", "data/raw/blackvinyl/blackvinyl_products.csv"]
    elif style == "legacy":
        scraper_args = ["--max-pages", "1" if args.lane == "detail" else str(args.limit), "--detail-limit", detail_limit]
    else:
        scraper_args = ["--max-pages", "1" if args.lane == "detail" else str(args.limit), "--detail-limit", detail_limit]
    scrape = [sys.executable, "-u", "-m", scraper, *scraper_args]
    print("[CUREDPLANT] legacy scrape:", " ".join(scrape), flush=True)
    result = subprocess.run(scrape, check=False)
    if result.returncode:
        return result.returncode

    import_command = [sys.executable, "-u", "-m", importer]
    if not args.write:
        import_command.append("--dry-run")
    print("[CUREDPLANT] importer:", " ".join(import_command), flush=True)
    return subprocess.run(import_command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
