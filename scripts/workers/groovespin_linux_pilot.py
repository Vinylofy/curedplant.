"""Read a bounded spread of GrooveSpin albums without writing production data."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

import requests

from scripts.importers.import_groovespin import SHOP_DEFINITION
from scripts.workers.groovespin_catalog import FIELDS, Source, parse_offers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("output/groovespin-linux-pilot"))
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("limit must be between 1 and 20 album pages")
    args.output.mkdir(parents=True, exist_ok=True)
    observed = datetime.now(timezone.utc).isoformat()
    rows, missing, rejected = [], 0, {}
    with requests.Session() as session:
        source = Source(session)
        albums = source.catalogue()
        # Spread samples across the sitemap rather than only testing the oldest IDs.
        count = min(args.limit, len(albums))
        selected = [albums[i * (len(albums) - 1) // max(count - 1, 1)] for i in range(count)]
        for _, url in selected:
            body = source.get(url, missing_ok=True)
            if body is None:
                missing += 1
                continue
            for row in parse_offers(body, url, observed):
                record, reason = SHOP_DEFINITION.row_mapper(row, len(rows) + 2)
                if record is None:
                    rejected[reason or "unknown"] = rejected.get(reason or "unknown", 0) + 1
                rows.append(row)
    with (args.output / "offers.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {"catalogue_albums": len(albums), "sampled_albums": count,
               "unavailable_albums": missing, "offers": len(rows),
               "valid_eans": sum(bool(row["ean"]) for row in rows),
               "importable_offers": len(rows) - sum(rejected.values()),
               "rejected_reasons": rejected, "database_writes": 0,
               "observed_at": observed}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)
    if not summary["importable_offers"]:
        raise SystemExit("No importable offers in pilot sample")


if __name__ == "__main__":
    main()
