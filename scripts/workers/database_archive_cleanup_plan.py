"""Report deletion eligibility for verified archive files without deleting rows."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from scripts.workers.database_archive_full import PROFILES


def verified_manifests(destination: Path, table: str, limit: int):
    selected = []
    for manifest in sorted((destination / "v1" / table).glob("*/batch-*.manifest.json")):
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        archive = manifest.parent / metadata["file"]
        if metadata.get("version") != 1 or metadata.get("table") != table:
            raise ValueError("archive manifest identity mismatch")
        if not archive.is_file():
            raise ValueError("archive file is missing")
        if hashlib.sha256(archive.read_bytes()).hexdigest() != metadata["sha256"]:
            raise ValueError("archive checksum mismatch")
        selected.append((metadata, archive))
        if len(selected) >= limit:
            break
    return selected


def archive_ids(metadata: dict, archive: Path):
    rows = [json.loads(line) for line in archive.read_bytes().splitlines() if line]
    ids = [str(row["id"]) for row in rows]
    if len(ids) != metadata["count"] or len(set(ids)) != len(ids):
        raise ValueError("archive row count or identity mismatch")
    return ids


def raw_counts(cur, ids: list[str]):
    cur.execute("""
        select count(*)::bigint,
               count(*) filter (where exists (
                   select 1 from public.staged_offers s where s.raw_scrape_id = r.id
               ))::bigint
          from public.raw_shop_scrapes r
         where r.id = any(%s::uuid[])
    """, (ids,))
    present, protected = cur.fetchone()
    return {"present": present, "protected": protected,
            "eligible": present - protected}


def price_counts(cur, ids: list[str]):
    cur.execute("""
        select count(*)::bigint,
               count(*) filter (where not exists (
                   select 1
                     from public.price_history newer
                    where newer.product_id = p.product_id
                      and newer.shop_id = p.shop_id
                      and (newer.captured_at, newer.id) > (p.captured_at, p.id)
               ))::bigint
          from public.price_history p
         where p.id = any(%s::uuid[])
    """, (ids,))
    present, protected = cur.fetchone()
    return {"present": present, "protected": protected,
            "eligible": present - protected}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--table", choices=sorted(PROFILES), required=True)
    parser.add_argument("--files", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.files <= 100 or args.destination.drive.upper() != "E:":
        parser.error("1..100 files and an E: destination are required")
    manifests = verified_manifests(args.destination, args.table, args.files)
    if not manifests:
        raise SystemExit("no verified archives found")

    import psycopg
    all_ids = []
    for metadata, archive in manifests:
        ids = archive_ids(metadata, archive)
        all_ids.extend(ids)
        print(json.dumps({"table": args.table, "file": archive.name,
                          "archived": len(ids), "verified": True,
                          "deleted": 0}), flush=True)
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("duplicate row identity across archive files")

    counter = raw_counts if args.table == "raw_shop_scrapes" else price_counts
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute("set transaction read only")
            cur.execute("set local statement_timeout = '60s'")
            counts = counter(cur, all_ids)
        conn.rollback()
    print(json.dumps({"table": args.table, "files": len(manifests),
                      "archived": len(all_ids), **counts,
                      "deleted": 0, "mode": "read_only_cleanup_plan"}), flush=True)


if __name__ == "__main__":
    main()
