#!/usr/bin/env python3
"""Capture the public per-shop catalog count without touching scraper code."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
from dotenv import load_dotenv


DEFAULT_WINDOW_HOURS = 48
TIME_ZONE = "Europe/Amsterdam"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Snapshot daily public shop catalog counts. Defaults to dry-run."
    )
    parser.add_argument("--write", action="store_true", help="Write the snapshot rows.")
    parser.add_argument(
        "--window-hours",
        type=int,
        default=DEFAULT_WINDOW_HOURS,
        help="Rolling freshness window used by the catalog query.",
    )
    parser.add_argument(
        "--day",
        help="Snapshot day in YYYY-MM-DD; defaults to Europe/Amsterdam today.",
    )
    return parser.parse_args()


def snapshot_day(day_arg: str | None) -> str:
    if day_arg:
        datetime.fromisoformat(f"{day_arg}T00:00:00+00:00")
        return day_arg
    return datetime.now(ZoneInfo(TIME_ZONE)).date().isoformat()


def load_environment() -> str:
    load_dotenv(".env.local", override=False)
    load_dotenv(".env", override=False)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is not set.")
    return database_url


SELECT_SQL = """
with eligible as (
    select
        p.shop_id,
        p.product_id,
        p.last_seen_at
    from public.prices p
    join public.products pr on pr.id = p.product_id
    where p.is_active = true
      and p.availability in ('in_stock', 'unknown')
      and p.last_seen_at >= now() - (%s * interval '1 hour')
      and coalesce(pr.format_label, '') not in ('CD', 'Cassette', 'DVD', 'Blu-ray')
      and coalesce(pr.gtin_normalized, pr.ean) is not null
), counts as (
    select
        shop_id,
        count(distinct product_id)::integer as published_title_count,
        count(*)::integer as active_offer_count,
        max(last_seen_at) as latest_eligible_seen_at
    from eligible
    group by shop_id
), active_offers as (
    select shop_id, max(last_seen_at) as latest_active_offer_seen_at
    from public.prices
    where is_active = true
    group by shop_id
)
select
    s.id as shop_id,
    s.name as webshop,
    coalesce(c.published_title_count, 0)::integer as published_title_count,
    coalesce(c.active_offer_count, 0)::integer as active_offer_count,
    c.latest_eligible_seen_at,
    ao.latest_active_offer_seen_at,
    case
        when c.published_title_count is not null then 'healthy'
        when ao.latest_active_offer_seen_at is not null
             and ao.latest_active_offer_seen_at < now() - (%s * interval '1 hour')
            then 'stale'
        else 'empty'
    end as data_status
from public.shops s
left join counts c on c.shop_id = s.id
left join active_offers ao on ao.shop_id = s.id
where s.is_active = true
order by published_title_count desc, s.name asc
"""


INSERT_SQL = """
insert into public.shop_catalog_daily (
    snapshot_day,
    shop_id,
    webshop,
    published_title_count,
    active_offer_count,
    latest_eligible_seen_at,
    latest_active_offer_seen_at,
    window_hours,
    data_status,
    captured_at
)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
on conflict (snapshot_day, shop_id) do update set
    webshop = excluded.webshop,
    published_title_count = excluded.published_title_count,
    active_offer_count = excluded.active_offer_count,
    latest_eligible_seen_at = excluded.latest_eligible_seen_at,
    latest_active_offer_seen_at = excluded.latest_active_offer_seen_at,
    window_hours = excluded.window_hours,
    data_status = excluded.data_status,
    captured_at = excluded.captured_at
"""


def main() -> int:
    args = parse_args()
    if args.window_hours < 1:
        raise SystemExit("--window-hours must be at least 1.")

    day = snapshot_day(args.day)
    database_url = load_environment()
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(SELECT_SQL, (args.window_hours, args.window_hours))
            rows = cur.fetchall()
            payload = [
                {
                    "shop_id": str(row[0]),
                    "webshop": row[1],
                    "published_title_count": row[2],
                    "active_offer_count": row[3],
                    "latest_eligible_seen_at": row[4].isoformat() if row[4] else None,
                    "latest_active_offer_seen_at": row[5].isoformat() if row[5] else None,
                    "data_status": row[6],
                }
                for row in rows
            ]
            print(
                json.dumps(
                    {
                        "snapshot_day": day,
                        "window_hours": args.window_hours,
                        "shops": len(payload),
                        "dry_run": not args.write,
                        "rows": payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                flush=True,
            )

            if not args.write:
                conn.rollback()
                return 0

            cur.executemany(
                INSERT_SQL,
                [
                    (
                        day,
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        row[4],
                        row[5],
                        args.window_hours,
                        row[6],
                    )
                    for row in rows
                ],
            )
        conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
