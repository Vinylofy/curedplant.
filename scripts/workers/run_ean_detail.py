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
    if args.write:
        command.append("--write")
    print("[CUREDPLANT] ean-detail:", " ".join(command), flush=True)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
