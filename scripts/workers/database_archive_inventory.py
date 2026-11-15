"""Read-only production facts needed before general historical archiving."""

import json
import os
from datetime import datetime, timezone


TABLES = ("raw_shop_scrapes", "price_history")


def collect(conn):
    report = {"measured_at": datetime.now(timezone.utc).isoformat(), "tables": {}}
    with conn.cursor() as cur:
        cur.execute("set transaction read only")
        cur.execute("set local statement_timeout = '30s'")
        cur.execute("""
            select c.relname, pg_total_relation_size(c.oid),
                   coalesce(s.n_live_tup, c.reltuples)::bigint,
                   coalesce(s.n_dead_tup, 0)::bigint
              from pg_class c
              join pg_namespace n on n.oid = c.relnamespace
              left join pg_stat_user_tables s on s.relid = c.oid
             where n.nspname = 'public' and c.relname = any(%s)
        """, (list(TABLES),))
        for name, size, live, dead in cur.fetchall():
            report["tables"][name] = {
                "total_bytes": size, "estimated_rows": live,
                "estimated_dead_rows": dead,
            }
        cur.execute("""
            select table_name, column_name, data_type, udt_name, is_nullable
              from information_schema.columns
             where table_schema = 'public' and table_name = any(%s)
             order by table_name, ordinal_position
        """, (list(TABLES),))
        for table, column, data_type, udt_name, nullable in cur.fetchall():
            report["tables"].setdefault(table, {})
            report["tables"][table].setdefault("columns", []).append({
                "name": column, "type": data_type, "udt": udt_name,
                "nullable": nullable == "YES",
            })
        cur.execute("""
            select t.relname, i.relname, pg_get_indexdef(i.oid),
                   pg_relation_size(i.oid)
              from pg_index x
              join pg_class i on i.oid = x.indexrelid
              join pg_class t on t.oid = x.indrelid
              join pg_namespace n on n.oid = t.relnamespace
             where n.nspname = 'public' and t.relname = any(%s)
             order by t.relname, i.relname
        """, (list(TABLES),))
        for table, name, definition, size in cur.fetchall():
            report["tables"][table].setdefault("indexes", []).append({
                "name": name, "definition": definition, "bytes": size,
            })
        cur.execute("""
            select confrelid::regclass::text, conrelid::regclass::text,
                   conname, pg_get_constraintdef(oid)
              from pg_constraint
             where contype = 'f'
               and confrelid in ('public.raw_shop_scrapes'::regclass,
                                 'public.price_history'::regclass)
             order by 1, 2, 3
        """)
        for referenced, referencing, name, definition in cur.fetchall():
            table = referenced.removeprefix("public.")
            report["tables"][table].setdefault("referenced_by", []).append({
                "table": referencing, "name": name, "definition": definition,
            })
        cur.execute("""
            select id::text, name from public.shops order by id
        """)
        shops = [{"id": row[0], "name": row[1]} for row in cur.fetchall()]
        report["shops"] = shops
        for table, timestamp in (("raw_shop_scrapes", "scraped_at"),
                                 ("price_history", "captured_at")):
            cur.execute(f"""
                select min({timestamp}), max({timestamp})
                  from public.{table}
            """)
            minimum, maximum = cur.fetchone()
            report["tables"][table]["minimum_timestamp"] = minimum.isoformat() if minimum else None
            report["tables"][table]["maximum_timestamp"] = maximum.isoformat() if maximum else None
    return report


def main():
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=False) as conn:
        report = collect(conn)
        conn.rollback()
    # Schema/index definitions are safe operational metadata; no row payloads.
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
