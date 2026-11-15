"""Delete only verified, redundantly backed-up historical archive rows."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts.workers.database_archive_full import PROFILES

CHUNK_SIZE = 500


def require_redundancy_confirmation(value: str):
    expected = "INDEPENDENT_COPY_VERIFIED"
    if value != expected or os.getenv("ARCHIVE_REDUNDANCY_ATTESTED") != expected:
        raise RuntimeError("independent archive copy has not been attested")


def pending_archives(destination: Path, table: str, limit: int):
    result = []
    for manifest in sorted((destination / "v1" / table).glob("*/batch-*.manifest.json")):
        marker = manifest.with_suffix(".cleanup.json")
        if marker.exists():
            continue
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        archive = manifest.parent / metadata["file"]
        body = archive.read_bytes()
        if metadata.get("version") != 1 or metadata.get("table") != table:
            raise ValueError("archive manifest identity mismatch")
        if hashlib.sha256(body).hexdigest() != metadata["sha256"]:
            raise ValueError("archive checksum mismatch")
        rows = [json.loads(line) for line in body.splitlines() if line]
        ids = [str(row["id"]) for row in rows]
        if len(ids) != metadata["count"] or len(set(ids)) != len(ids):
            raise ValueError("archive row count or identity mismatch")
        result.append((manifest, marker, metadata, ids))
        if len(result) >= limit:
            break
    return result


def delete_chunk(cur, table: str, ids: list[str]):
    if table == "raw_shop_scrapes":
        cur.execute("""
            delete from public.raw_shop_scrapes r
             where r.id = any(%s::uuid[])
               and not exists (
                   select 1 from public.staged_offers s where s.raw_scrape_id = r.id
               )
            returning r.id::text
        """, (ids,))
    else:
        cur.execute("""
            delete from public.price_history p
             where p.id = any(%s::uuid[])
               and exists (
                   select 1 from public.price_history newer
                    where newer.product_id = p.product_id
                      and newer.shop_id = p.shop_id
                      and (newer.captured_at, newer.id) > (p.captured_at, p.id)
               )
            returning p.id::text
        """, (ids,))
    return [row[0] for row in cur.fetchall()]


def write_marker(marker: Path, metadata: dict, deleted: int, retained: int):
    result = {
        "version": 1, "table": metadata["table"], "sha256": metadata["sha256"],
        "archive_file": metadata["file"], "archive_count": metadata["count"],
        "deleted": deleted, "retained_by_safety_rule": retained,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    pending = marker.with_suffix(".pending")
    with pending.open("x", encoding="utf-8") as output:
        json.dump(result, output, separators=(",", ":"))
        output.flush()
        os.fsync(output.fileno())
    pending.replace(marker)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--table", choices=sorted(PROFILES), required=True)
    parser.add_argument("--files", type=int, default=10)
    parser.add_argument("--confirm-redundancy", required=True)
    args = parser.parse_args()
    if args.destination.drive.upper() != "E:" or not 1 <= args.files <= 100:
        parser.error("an E: destination and 1..100 files are required")
    require_redundancy_confirmation(args.confirm_redundancy)
    archives = pending_archives(args.destination, args.table, args.files)

    import psycopg
    total_deleted = 0
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        for manifest, marker, metadata, ids in archives:
            deleted = 0
            for start in range(0, len(ids), CHUNK_SIZE):
                with conn.cursor() as cur:
                    cur.execute("set local statement_timeout = '30s'")
                    deleted += len(delete_chunk(cur, args.table, ids[start:start + CHUNK_SIZE]))
                conn.commit()
            retained = metadata["count"] - deleted
            write_marker(marker, metadata, deleted, retained)
            total_deleted += deleted
            print(json.dumps({"table": args.table, "manifest": manifest.name,
                              "deleted": deleted, "retained": retained}), flush=True)
    print(json.dumps({"table": args.table, "files": len(archives),
                      "deleted": total_deleted, "mode": "bounded_cleanup"}), flush=True)


if __name__ == "__main__":
    main()
