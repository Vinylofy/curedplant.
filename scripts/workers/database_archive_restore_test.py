"""Restore verified E: archive samples into transaction-local PostgreSQL tables."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from scripts.workers.database_archive_full import PROFILES


def checkpoint_manifests(destination: Path, table: str, limit: int):
    checkpoints = sorted((destination / "v1" / table).glob("*/checkpoint.json"))
    records = []
    for checkpoint in checkpoints[:limit]:
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        if state.get("version") != 1 or state.get("table") != table:
            raise ValueError("restore checkpoint identity mismatch")
        manifest = checkpoint.parent / state["manifest"]
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        archive = checkpoint.parent / metadata["file"]
        if hashlib.sha256(archive.read_bytes()).hexdigest() != metadata["sha256"]:
            raise ValueError("restore source checksum mismatch")
        records.append((metadata, archive))
    return records


def restore_file(conn, table: str, metadata: dict, archive: Path):
    rows = [line.decode("utf-8") for line in archive.read_bytes().splitlines() if line]
    if len(rows) != metadata["count"]:
        raise ValueError("restore source count mismatch")
    temporary = f"archive_restore_{table}"
    with conn.cursor() as cur:
        cur.execute(f"drop table if exists pg_temp.{temporary}")
        cur.execute(f"""
            create temp table {temporary}
              (like public.{table} including defaults including generated including constraints)
              on commit drop
        """)
        for payload in rows:
            cur.execute(f"""
                insert into pg_temp.{temporary}
                select restored.*
                  from jsonb_populate_record(null::public.{table}, %s::jsonb) restored
            """, (payload,))
        cur.execute(f"select count(*), count(distinct id) from pg_temp.{temporary}")
        count, distinct_ids = cur.fetchone()
        if count != metadata["count"] or distinct_ids != count:
            raise RuntimeError("temporary restore count or identity mismatch")
        cur.execute(f"select min(id)::text, max(id)::text from pg_temp.{temporary}")
        restored_ids = set(cur.fetchone())
        source_ids = {str(json.loads(row)["id"]) for row in rows}
        if not restored_ids.issubset(source_ids):
            raise RuntimeError("temporary restore IDs mismatch")
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--table", choices=sorted(PROFILES), required=True)
    parser.add_argument("--files", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.files <= 10 or args.destination.drive.upper() != "E:":
        parser.error("1..10 files and an E: destination are required")
    records = checkpoint_manifests(args.destination, args.table, args.files)
    if not records:
        raise SystemExit("no verified checkpoint archives found")

    import psycopg
    total = 0
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        for metadata, archive in records:
            count = restore_file(conn, args.table, metadata, archive)
            total += count
            conn.rollback()
            print(json.dumps({"table": args.table, "file": archive.name,
                              "restored": count, "persistent_writes": 0}), flush=True)
    print(json.dumps({"table": args.table, "files": len(records),
                      "restored": total, "persistent_writes": 0}), flush=True)


if __name__ == "__main__":
    main()
