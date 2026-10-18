"""Collect the next, previously unprocessed EAN details for one approved shop."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re

import requests

from scripts.workers.ean_progress import GitHubProgress, day_key, reserve, validate_state
from scripts.workers.ean_queue import EanQueue
from scripts.workers.ean_sources import EanSource, GREEN

MAX_DISCOVERY_PAGES = 10


def error_text(exc):
    text = str(exc)
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        text = text.replace(database_url, "<database connection>")
    return re.sub(r"postgres(?:ql)?://\S+|password=\S+", "<redacted>", text)


def execute(shop, limit, write, *, progress=None, queue=None, source_factory=EanSource, today=None):
    progress, queue = progress or GitHubProgress(shop), queue or EanQueue()
    today = today or day_key()
    summary = {"shop": shop, "day": today, "write": write, "requested": limit,
               "reserved": 0, "selected": 0, "attempted": 0, "details_started": 0, "valid_eans": 0,
               "missing_ean": 0, "unavailable": 0, "excluded_non_vinyl": 0,
               "technical_errors": 0, "claim_skips": 0, "discovery_pages": 0,
               "requeued_for_repair": 0, "refunded_reservations": 0,
               "price_writes": 0, "records": [], "errors": []}
    source, state, reservation_saved = None, None, False
    try:
        state = copy.deepcopy(validate_state(progress.load(), shop))
        allocated = reserve(state, limit, today) if write else limit
        summary["reserved"] = allocated if write else 0
        if allocated == 0:
            summary["outcome"] = "daily_budget_exhausted"
            return summary
        if write:
            # Reserve before any source requests. A repeated manual run cannot
            # exceed 100 slots on the same Europe/Amsterdam calendar day.
            progress.save(state)
            reservation_saved = True
        if write and shop == "fiftiesstore":
            summary["requeued_for_repair"] = queue.requeue_fifties_layout_misses()
        selected = queue.candidates(shop, allocated)
        selected_by_url = {row["source_url"]: row for row in selected}
        cursor = state["cursor"]
        exhausted_on = cursor.get("exhausted_on")
        if cursor.get("exhausted") and exhausted_on and today >= (datetime.fromisoformat(exhausted_on) + timedelta(days=7)).date().isoformat():
            cursor = state["cursor"] = {"page": 1, "seed": 0}
        source = source_factory(shop)
        for _ in range(MAX_DISCOVERY_PAGES):
            if len(selected_by_url) >= allocated or cursor.get("exhausted") or cursor.get("registry_only"):
                break
            try:
                rows, following = source.catalog(cursor)
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code not in {404, 410} or cursor["page"] == 1:
                    raise
                rows, following = [], source.terminal(cursor)
            summary["discovery_pages"] += 1
            if following.get("exhausted"):
                following["exhausted_on"] = today
            if write:
                queue.register(shop, rows)
                selected_by_url = {row["source_url"]: row for row in queue.candidates(shop, allocated)}
            else:
                for row in queue.fresh_catalog_rows(shop, rows):
                    selected_by_url.setdefault(row["source_url"], row)
            cursor = state["cursor"] = following
            if write:
                progress.save(state)
        selected = list(selected_by_url.values())[:allocated]
        summary["selected"] = len(selected)
        if not selected:
            summary["outcome"] = "waiting_for_source_registry" if cursor.get("registry_only") else "catalogue_exhausted" if cursor.get("exhausted") else "discovery_continues_next_run"
        for row in selected:
            if write and not queue.claim(shop, row):
                summary["claim_skips"] += 1
                continue
            result = {"source_url": row["source_url"], "day": today}
            stop = False
            # Count before fetch/commit: a failed product write still used its
            # detail slot, but a skipped claim or unused batch did not.
            summary["details_started"] += 1
            try:
                result.update(source.detail(row))
            except Exception as exc:
                result.update(ean=None, error=error_text(exc))
                summary["errors"].append({"url": row["source_url"], "error": result["error"]})
                status = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else None
                stop = status in {403, 429} or len(summary["errors"]) >= 3
            if write:
                # Raw enrichment, product identity and queue completion commit
                # together. A DB failure leaves an expiring claim, not a done row.
                queue.finish(shop, row, result)
            summary["attempted"] += 1
            counter = ("technical_errors" if result.get("error") else "unavailable" if result.get("unavailable")
                       else "excluded_non_vinyl" if result.get("excluded_reason")
                       else "valid_eans" if result.get("ean") else "missing_ean")
            summary[counter] += 1
            summary["records"].append(result)
            print("[DAILY-EAN]", json.dumps(result, ensure_ascii=False), flush=True)
            if stop:
                break
        if selected and not summary["errors"] and not summary["valid_eans"]:
            summary["errors"].append({"error": "No valid GTIN in the new detail batch; source review required"})
        summary.setdefault("outcome", "completed")
    except Exception as exc:
        summary["errors"].append({"error": error_text(exc)})
        summary["outcome"] = "failed"
    finally:
        if source is not None:
            summary["transport"] = source.events
            source.close()
        if state is not None:
            summary["next_cursor"] = state["cursor"]
            summary["daily_reserved"] = state["budget"]["reserved"] if write else None
        summary["status"] = "red" if summary["errors"] else "waiting" if not summary["attempted"] else "green"
        if write and state is not None and reservation_saved:
            unused = allocated - summary["details_started"]
            state["budget"]["reserved"] -= unused
            state["last_result"] = {key: summary[key] for key in
                ("day", "attempted", "details_started", "valid_eans", "missing_ean", "unavailable", "excluded_non_vinyl", "technical_errors", "status", "outcome")}
            try:
                progress.save(state)
                summary["refunded_reservations"] = unused
                summary["daily_reserved"] = state["budget"]["reserved"]
            except Exception as exc:
                summary["errors"].append({"error": error_text(exc)})
                summary["status"] = "red"
        path = Path("output/daily-ean") / f"{shop}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n")
        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a") as handle:
                handle.write(f"### {shop}: {summary['status']} — {summary.get('outcome')}\n\n"
                    f"Nieuwe details: **{summary['attempted']}**; geldige GTIN: **{summary['valid_eans']}**; "
                    f"EAN ontbreekt: {summary['missing_ean']}; technische detailfouten: {summary['technical_errors']}; "
                    f"verwijderde producten: {summary['unavailable']}; geen vinyl: {summary['excluded_non_vinyl']}; "
                    f"overige fouten: {len(summary['errors']) - summary['technical_errors']}.\n\n"
                    f"Gereserveerd vandaag: {summary.get('daily_reserved')}; prijswrites: **0**. "
                    f"Volgende cataloguspositie: `{summary.get('next_cursor')}`.\n\n"
                    + "\n".join(f"- {error['error']}" for error in summary["errors"]) + "\n")
        print("[DAILY-EAN-SUMMARY]", json.dumps({k: v for k, v in summary.items() if k != "records"}, default=str), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=GREEN, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("daily EAN limit must be 1..100")
    result = execute(args.worker, args.limit, args.write)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
