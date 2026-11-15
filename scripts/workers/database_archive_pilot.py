"""Bounded, read-only export of old raw rows to the Windows runner E: drive."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

BOL_NL_SHOP_ID = "f08437c2-1d85-47a6-94f9-33a55612d5cc"


def export_batch(conn, destination: Path, cutoff: datetime, limit: int, run_id: str):
    if not 1 <= limit <= 500:
        raise ValueError("limit must be 1..500")
    if destination.drive.upper() != "E:" or not destination.is_dir():
        raise ValueError("existing E: destination required")
    with conn.cursor() as cur:
        cur.execute("set transaction read only")
        cur.execute("set local statement_timeout = '20s'")
        cur.execute("""
            select r.id::text, r.scraped_at, row_to_json(r)::text
              from public.raw_shop_scrapes r
             where r.shop_id = %s
               and r.scraped_at < %s
               and r.parse_status = 'bol_affiliate_evidence'
             order by r.scraped_at desc
             limit %s
        """, (BOL_NL_SHOP_ID, cutoff, limit))
        rows = cur.fetchall()
    if not rows:
        return {"status": "empty", "rows": 0, "deleted": 0}
    body = "".join(row[2] + "\n" for row in rows).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    target = destination / f"raw_shop_scrapes-{run_id}-{digest}.jsonl"
    manifest = target.with_suffix(".manifest.json")
    if target.exists() or manifest.exists():
        raise FileExistsError("archive file exists; refusing overwrite")
    pending = target.with_suffix(".pending")
    try:
        with pending.open("xb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        if hashlib.sha256(pending.read_bytes()).hexdigest() != digest:
            raise RuntimeError("write verification failed")
        pending.rename(target)
        metadata = {"table": "public.raw_shop_scrapes", "format": "postgres-row-to-json-v1",
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "cutoff": cutoff.isoformat(), "count": len(rows), "bytes": len(body),
                    "first_id": rows[0][0], "last_id": rows[-1][0],
                    "first_scraped_at": rows[0][1].isoformat(),
                    "last_scraped_at": rows[-1][1].isoformat(),
                    "sha256": digest, "file": target.name, "deleted": 0}
        with manifest.open("x", encoding="utf-8") as output:
            json.dump(metadata, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        restored = target.read_bytes()
        parsed = [json.loads(line) for line in restored.splitlines()]
        if hashlib.sha256(restored).hexdigest() != digest or len(parsed) != len(rows):
            raise RuntimeError("destination count/checksum mismatch")
        if [str(row["id"]) for row in parsed] != [row[0] for row in rows]:
            raise RuntimeError("destination IDs mismatch")
        return {"status": "verified_local_copy", "rows": len(rows), "deleted": 0,
                "file": target.name, "sha256": digest}
    finally:
        pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--min-age-days", type=int, default=1)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if args.min_age_days < 1 or not args.run_id.isdigit():
        parser.error("age >= 1 day and a numeric run ID are required")
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        result = export_batch(conn, args.destination,
                              datetime.now(timezone.utc) - timedelta(days=args.min_age_days),
                              args.limit, args.run_id)
        conn.rollback()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
