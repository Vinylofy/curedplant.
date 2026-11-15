"""Resumable, verified copies of historical raw and price rows to E:."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROFILES = {
    "raw_shop_scrapes": {"timestamp": "scraped_at", "min_age": 30, "shop_cast": "text"},
    "price_history": {"timestamp": "captured_at", "min_age": 90, "shop_cast": "uuid"},
}
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def source_key(table: str, shop_id: str) -> str:
    digest = hashlib.sha256(shop_id.encode("utf-8")).hexdigest()[:20]
    return f"{table}-{digest}"


def paths(destination: Path, table: str, shop_id: str):
    root = destination / "v1" / table / source_key(table, shop_id)
    return root, root / "checkpoint.json"


def read_checkpoint(root: Path, checkpoint: Path, table: str, shop_id: str):
    if not checkpoint.exists():
        return "0001-01-01T00:00:00+00:00", ZERO_UUID
    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    if state.get("version") != 1 or state.get("table") != table or state.get("shop_id") != shop_id:
        raise ValueError("checkpoint identity mismatch")
    manifest = root / state["manifest"]
    if not manifest.is_file():
        raise ValueError("checkpoint manifest missing")
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("last_id") != state.get("last_id") or metadata.get("last_timestamp") != state.get("last_timestamp"):
        raise ValueError("checkpoint does not match manifest")
    archive = root / metadata["file"]
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError("checkpoint archive missing or corrupt")
    return state["last_timestamp"], state["last_id"]


def write_checkpoint(root: Path, checkpoint: Path, metadata: dict, manifest: Path):
    state = {"version": 1, "table": metadata["table"], "shop_id": metadata["shop_id"],
             "last_timestamp": metadata["last_timestamp"], "last_id": metadata["last_id"],
             "manifest": manifest.name}
    pending = root / "checkpoint.pending"
    with pending.open("w", encoding="utf-8") as output:
        json.dump(state, output, separators=(",", ":"))
        output.flush()
        os.fsync(output.fileno())
    pending.replace(checkpoint)


def table_schema(conn, table: str):
    with conn.cursor() as cur:
        cur.execute("""
            select column_name, data_type, udt_name, is_nullable
              from information_schema.columns
             where table_schema='public' and table_name=%s
             order by ordinal_position
        """, (table,))
        return [{"name": name, "type": kind, "udt": udt,
                 "nullable": nullable == "YES"} for name, kind, udt, nullable in cur.fetchall()]


def shop_ids(conn, table: str, cutoff: datetime):
    timestamp = PROFILES[table]["timestamp"]
    with conn.cursor() as cur:
        cur.execute("set local statement_timeout = '60s'")
        cur.execute(f"""
            select distinct shop_id::text
              from public.{table}
             where {timestamp} < %s
             order by 1
        """, (cutoff,))
        return [row[0] for row in cur.fetchall()]


def verify_restore_shape(conn, table: str, serialized_rows: list[str], expected_ids: list[str]):
    samples = [serialized_rows[0]]
    ids = [expected_ids[0]]
    if len(serialized_rows) > 1:
        samples.append(serialized_rows[-1])
        ids.append(expected_ids[-1])
    with conn.cursor() as cur:
        for payload, expected_id in zip(samples, ids):
            cur.execute(f"""
                select restored.id::text
                  from jsonb_populate_record(null::public.{table}, %s::jsonb) restored
            """, (payload,))
            if cur.fetchone()[0] != expected_id:
                raise RuntimeError("database restore conversion mismatch")


def export_batch(conn, destination: Path, table: str, shop_id: str,
                 cutoff: datetime, limit: int, schema: list[dict]):
    if table not in PROFILES or not 1 <= limit <= 5000:
        raise ValueError("invalid table or limit")
    root, checkpoint = paths(destination, table, shop_id)
    root.mkdir(parents=True, exist_ok=True)
    last_timestamp, last_id = read_checkpoint(root, checkpoint, table, shop_id)
    profile = PROFILES[table]
    timestamp = profile["timestamp"]
    shop_parameter = "%s::uuid" if profile["shop_cast"] == "uuid" else "%s"
    with conn.cursor() as cur:
        cur.execute("set transaction read only")
        cur.execute("set local statement_timeout = '30s'")
        cur.execute(f"""
            select id::text, {timestamp}, row_to_json(source)::text
              from public.{table} source
             where shop_id = {shop_parameter}
               and {timestamp} < %s
               and ({timestamp}, id) > (%s::timestamptz, %s::uuid)
             order by {timestamp} asc, id asc
             limit %s
        """, (shop_id, cutoff, last_timestamp, last_id, limit))
        rows = cur.fetchall()
    if not rows:
        return {"status": "empty", "rows": 0, "deleted": 0, "shop_id": shop_id}

    serialized = [row[2] for row in rows]
    body = ("\n".join(serialized) + "\n").encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    archive = root / f"batch-{digest}.jsonl"
    manifest = root / f"batch-{digest}.manifest.json"
    metadata = {"version": 1, "table": table, "shop_id": shop_id,
                "format": "postgres-row-to-json-v1", "schema": schema,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "cutoff": cutoff.isoformat(), "count": len(rows), "bytes": len(body),
                "first_id": rows[0][0], "last_id": rows[-1][0],
                "first_timestamp": rows[0][1].isoformat(),
                "last_timestamp": rows[-1][1].isoformat(),
                "sha256": digest, "file": archive.name, "deleted": 0}
    if archive.exists() or manifest.exists():
        if not archive.is_file() or not manifest.is_file():
            raise RuntimeError("incomplete previous export")
        previous = json.loads(manifest.read_text(encoding="utf-8"))
        if previous != metadata or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            # exported_at differs on a retry, so compare immutable fields only.
            retry_variant = {"exported_at", "cutoff"}
            immutable = {key: value for key, value in metadata.items() if key not in retry_variant}
            previous_immutable = {key: value for key, value in previous.items() if key not in retry_variant}
            if previous_immutable != immutable or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
                raise RuntimeError("previous archive differs from current batch")
        write_checkpoint(root, checkpoint, previous, manifest)
        return {"status": "resumed_verified_copy", "rows": len(rows), "deleted": 0,
                "shop_id": shop_id, "file": archive.name, "sha256": digest}

    pending = root / f"batch-{digest}.pending"
    try:
        with pending.open("xb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        if hashlib.sha256(pending.read_bytes()).hexdigest() != digest:
            raise RuntimeError("write verification failed")
        pending.replace(archive)
        with manifest.open("x", encoding="utf-8") as output:
            json.dump(metadata, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        restored = archive.read_bytes()
        parsed = [json.loads(line) for line in restored.splitlines()]
        if hashlib.sha256(restored).hexdigest() != digest or len(parsed) != len(rows):
            raise RuntimeError("destination count/checksum mismatch")
        if [str(row["id"]) for row in parsed] != [row[0] for row in rows]:
            raise RuntimeError("destination IDs mismatch")
        verify_restore_shape(conn, table, serialized, [row[0] for row in rows])
        write_checkpoint(root, checkpoint, metadata, manifest)
        return {"status": "verified_local_copy", "rows": len(rows), "deleted": 0,
                "shop_id": shop_id, "file": archive.name, "sha256": digest}
    finally:
        pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--table", choices=sorted(PROFILES), required=True)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--batches", type=int, default=10)
    parser.add_argument("--min-age-days", type=int)
    args = parser.parse_args()
    if not 1 <= args.limit <= 5000 or not 1 <= args.batches <= 500:
        parser.error("limit 1..5000 and batches 1..500 are required")
    if args.destination.drive.upper() != "E:" or not args.destination.is_dir():
        parser.error("existing E: destination is required")

    import psycopg
    age = args.min_age_days or PROFILES[args.table]["min_age"]
    if age < PROFILES[args.table]["min_age"]:
        parser.error("minimum age is below the guarded retention floor")
    cutoff = datetime.now(timezone.utc) - timedelta(days=age)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        schema = table_schema(conn, args.table)
        sources = shop_ids(conn, args.table, cutoff)
        conn.rollback()
        total = 0
        batch = 0
        while batch < args.batches:
            progressed = False
            for shop_id in sources:
                if batch >= args.batches:
                    break
                result = export_batch(conn, args.destination, args.table, shop_id,
                                      cutoff, args.limit, schema)
                conn.rollback()
                if result["rows"] == 0:
                    continue
                progressed = True
                batch += 1
                total += result["rows"]
                print(json.dumps({"batch": batch, "table": args.table, **result}), flush=True)
            if not progressed:
                break
    print(json.dumps({"table": args.table, "sources": len(sources),
                      "batches": batch, "total_exported": total, "deleted": 0}), flush=True)


if __name__ == "__main__":
    main()
