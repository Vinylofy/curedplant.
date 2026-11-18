"""Read-only progress report for the E: historical database archive."""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.workers.database_archive_full import PROFILES, retention_days


def archived_rows(destination: Path, table: str) -> int:
    total = 0
    seen = set()
    for path in (destination / "v1" / table).glob("*/batch-*.manifest.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        identity = (metadata.get("sha256"), metadata.get("file"))
        if metadata.get("version") != 1 or metadata.get("table") != table:
            raise ValueError("archive manifest identity mismatch")
        if identity in seen:
            raise ValueError("duplicate archive manifest")
        seen.add(identity)
        total += int(metadata["count"])
    return total


def database_counts(conn, table: str, cutoff: datetime):
    timestamp = PROFILES[table]["timestamp"]
    with conn.cursor() as cur:
        cur.execute("set transaction read only")
        cur.execute("set local statement_timeout = '180s'")
        cur.execute(f"""
            select count(*)::bigint,
                   count(*) filter (where {timestamp} < %s)::bigint
              from public.{table}
        """, (cutoff,))
        return cur.fetchone()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.destination.drive.upper() != "E:":
        parser.error("an E: destination is required")

    import psycopg
    report = {"measured_at": datetime.now(timezone.utc).isoformat(), "deleted": 0,
              "tables": {}}
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        measured_at = datetime.now(timezone.utc)
        for table in PROFILES:
            days = retention_days(table, measured_at)
            cutoff = measured_at - timedelta(days=days)
            total, historical = database_counts(conn, table, cutoff)
            conn.rollback()
            archived = archived_rows(args.destination, table)
            report["tables"][table] = {
                "retention_days": days, "database_rows": total,
                "historical_rows": historical, "archived_rows": archived,
                "remaining_to_archive": max(0, historical - archived),
            }
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
