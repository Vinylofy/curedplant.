"""Bounded price-source evidence for the two Linux transport migrations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from scripts.scrapers.usf.jobs.live_detail_pilot import new_session
from scripts.workers.run_windows_baseline import positive_price


def run(shop, limit):
    summary = {"shop": shop, "source_version": "current", "write": False,
               "time": datetime.now(timezone.utc).isoformat(), "records": [], "errors": []}
    session = new_session(shop)
    try:
        if shop == "northendhaarlem":
            from scripts.scrapers.usf.jobs import refresh_northendhaarlem_listing_prices as source
            rows = source.discover_listing_rows(category_limit=1, max_pages_per_category=limit,
                       delay_seconds=0, session=session)
            links = [row.link for row in rows]
        else:
            from scripts.scrapers.usf.jobs import refresh_soundsvenlo_listing_prices as source
            links, seen = [], set()
            for page in range(1, limit + 1):
                url = source.listing_url_for_page(page)
                html = source.fetch_listing_html(session, url)
                parsed, _ = source.parse_listing_page(html, listing_url=url, page=page,
                              seen_at=datetime.now(timezone.utc), debug=False)
                fresh = [link for link in parsed if link.source_url not in seen]
                if not fresh:
                    break
                links.extend(fresh)
                seen.update(link.source_url for link in fresh)
        for link in links:
            record = {"url": link.source_url, "price": link.payload.get("price"),
                      "title": link.payload.get("title_raw") or link.payload.get("title"),
                      "availability": link.payload.get("availability")}
            summary["records"].append(record)
            if not positive_price(record["price"]):
                summary["errors"].append({"error": "Missing/invalid price", "url": link.source_url})
    except Exception as exc:
        summary["errors"].append({"error": str(exc)})
    finally:
        summary["transport"] = session.events
        session.close()
    summary["products"] = len(summary["records"])
    summary["unique_prices"] = len({str(row["price"]) for row in summary["records"]})
    summary["status"] = "green" if summary["products"] and not summary["errors"] else "red"
    summary["scope"] = "listing price extraction only; no detail or database certification"
    path = Path("output/price-pilots") / f"{shop}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write(f"### {shop} | Linux price pilot: {summary['status']}\n\n"
                         f"Products: {summary['products']}; distinct prices: {summary['unique_prices']}; "
                         f"errors: {len(summary['errors'])}. Database writes: 0.\n\n"
                         + "\n".join(f"- {error['error']}" for error in summary["errors"]) + "\n")
    print("[LIVE-PRICE-SUMMARY]", json.dumps({k: v for k, v in summary.items() if k != "records"}), flush=True)
    return 0 if summary["status"] == "green" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop", choices=("northendhaarlem", "soundsvenlo"), required=True)
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.limit <= 3:
        parser.error("price pilot limit must be 1..3 pages in the first category")
    return run(args.shop, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
