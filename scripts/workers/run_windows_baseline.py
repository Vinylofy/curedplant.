"""Read-only Linux pilots of the exact shop sources used by successful Windows runs.

Only native fetch and parse functions are called, never their database pipelines.
Published crawl intervals and a single attempt bound the older transport. EANs
are compared with the repaired product-scoped parser, not trusted by checksum alone.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
from urllib.parse import urlparse

import requests

from scripts.importers.common import strict_normalize_gtin

SHOPS = ("northendhaarlem", "soundsvenlo")
ROOT = Path(__file__).with_name("windows_baseline")
INTERVALS = {"northendhaarlem": 30.0, "soundsvenlo": 10.0}
HOSTS = {"northendhaarlem": {"northendhaarlem.nl", "www.northendhaarlem.nl"},
         "soundsvenlo": {"sounds-venlo.nl", "www.sounds-venlo.nl"}}


def command_for(shop, lane, limit, write=False):
    maximum = 3 if lane == "price" else 25
    if write:
        raise SystemExit("Windows baseline is read-only; write=true is not allowed")
    if shop not in SHOPS or lane not in {"price", "detail"} or not 1 <= limit <= maximum:
        raise SystemExit(f"Invalid baseline request: shop={shop}, lane={lane}, limit={limit}; maximum={maximum}")
    return [sys.executable, "-u", "-m", "scripts.workers.run_windows_baseline",
            "--shop", shop, "--lane", lane, "--limit", str(limit)]


def source_modules(shop):
    manifest = json.loads((ROOT / "manifest.json").read_text())
    modules = []
    for name in (f"refresh_{shop}_listing_prices", f"detail_{shop}"):
        filename = name + ".py"
        digest = hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        if digest != manifest["files"][filename]["sha256"]:
            raise ValueError(f"Windows source checksum differs: {filename}")
        modules.append(importlib.import_module(f"scripts.workers.windows_baseline.{name}"))
    return manifest, modules[0], modules[1]


class SourceBlocked(RuntimeError):
    pass


class ObservedSession(requests.Session):
    def __init__(self, owner, headers):
        super().__init__()
        self.owner = owner
        self.headers.update(headers)

    def get(self, url, **kwargs):
        self.owner.pace()
        try:
            response = super().get(url, **kwargs)
        except requests.RequestException:
            # The original Venlo listing code may next open its ordinary browser.
            self.owner.pace()
            raise
        self.owner.observe(url, response.status_code, response.text, "windows_http",
                           challenge=response.headers.get("cf-mitigated") == "challenge")
        if response.status_code == 429:
            # The old listing helper catches RequestException and opens a browser;
            # a rate limit must instead end this pilot without a second request.
            raise SourceBlocked(f"HTTP 429: {url}")
        if response.status_code == 403:
            self.owner.pace()
        return response


class BaselineTransport:
    def __init__(self, shop, listing, detail, *, clock=time.monotonic, sleeper=time.sleep):
        self.shop, self.listing, self.detail = shop, listing, detail
        self.clock, self.sleeper, self.last_request = clock, sleeper, None
        self.events = []
        self.listing_session = self.detail_session = None
        if shop == "soundsvenlo":
            self.listing_session = ObservedSession(self, listing.DEFAULT_HEADERS)
            self.detail_session = ObservedSession(self, {"User-Agent": detail.DEFAULT_USER_AGENT})

    def pace(self):
        if self.last_request is not None:
            remaining = INTERVALS[self.shop] - (self.clock() - self.last_request)
            if remaining > 0:
                self.sleeper(remaining)
        self.last_request = self.clock()

    def observe(self, url, status, html, transport, **extra):
        self.events.append({"url": url, "status": status, "transport": transport,
                            "sha256": hashlib.sha256(html.encode()).hexdigest(), **extra})

    def fetch(self, url, lane, referer=None):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in HOSTS[self.shop]:
            raise ValueError(f"Unexpected source URL: {url}")
        if self.shop == "northendhaarlem":
            self.pace()
            source = self.listing if lane == "price" else self.detail
            status, html = source.fetch_html(url, attempts=1)
            self.observe(url, status, html, "windows_http")
            if status >= 400:
                raise SourceBlocked(f"HTTP {status}: {url}")
            return html
        if lane == "detail":
            response = self.detail_session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        start = len(self.events)
        try:
            html = self.listing.fetch_listing_html(self.listing_session, url, referer=referer)
        except Exception as exc:
            # The original browser helper exposes a failing status in its error,
            # but does not return response headers or a successful HTTP status.
            match = re.search(r"status=(\d{3})", str(exc))
            if match:
                self.observe(url, int(match.group(1)), "", "windows_playwright", error=str(exc))
            raise
        if not self.events[start:] or self.events[-1]["status"] != 200:
            self.observe(url, None, html, "windows_playwright", returned_html=True)
        return html

    def close(self):
        for session in (self.listing_session, self.detail_session):
            if session:
                session.close()


def listing_rows(shop, source, transport, page):
    now = datetime.now(timezone.utc)
    if shop == "northendhaarlem":
        seed = source.CATEGORY_SEEDS[0]
        url = source.category_url(seed, page)
        html = transport.fetch(url, "price")
        return [row.link for row in source.parse_listing_page(html, discovery_url=url,
                seed=seed, page=page, seen_at=now.isoformat())]
    url = source.listing_url_for_page(page)
    html = transport.fetch(url, "price", referer=source.BASE_URL + "/" if page == 1
                           else source.listing_url_for_page(page - 1))
    links, _ = source.parse_listing_page(html, listing_url=url, page=page, seen_at=now, debug=False)
    return links


def detail_record(shop, old, html, link):
    if shop == "northendhaarlem":
        from scripts.scrapers.usf.jobs import detail_northendhaarlem as current
        baseline = old.parse_detail_page(html, listing_payload=link.payload)
        checked = current.parse_detail_page(html, listing_payload=link.payload)
        raw, validated = baseline["ean"], checked["ean"]
        title, issue = checked["title_raw"], checked.get("ean_issue")
    else:
        from scripts.scrapers.usf.jobs import detail_soundsvenlo as current
        raw = old.extract_ean(html, link.source_url)
        checked = current.ean_evidence(html, link.source_url)
        validated, issue = checked["ean"], checked["issue"]
        title = current.build_title_raw(link.payload, html)
    normalized = strict_normalize_gtin(raw)
    return {"title": title, "baseline_ean": raw, "baseline_gtin": normalized,
            "validated_product_gtin": validated, "identity_disagreement": normalized != validated,
            "ean": normalized if normalized == validated else None, "issue": issue,
            "detail_sha256": hashlib.sha256(html.encode()).hexdigest()}


def positive_price(value):
    try:
        price = Decimal(str(value))
        return price.is_finite() and price > 0
    except (InvalidOperation, ValueError):
        return False


def run(shop, lane, limit):
    manifest, listing, detail = source_modules(shop)
    summary = {"shop": shop, "lane": lane, "source_version": "windows-baseline",
        "source_commit": manifest["commit"], "source_repository": manifest["repository"],
        "windows_reference_run": manifest["windows_runs"][shop], "write": False,
        "database_writes": 0, "time": datetime.now(timezone.utc).isoformat(),
        "runtime": {"python": platform.python_version(), "os": platform.system(),
                    **{name: version(name) for name in ("requests", "beautifulsoup4")}},
        "listing_pages": 0, "discovered": 0, "fetched": 0, "valid_eans": 0,
        "missing_ean": 0, "identity_disagreements": 0, "errors": [], "records": []}
    transport = BaselineTransport(shop, listing, detail)
    seen = set()
    try:
        for page in range(1, (limit if lane == "price" else 1) + 1):
            links = listing_rows(shop, listing, transport, page)
            summary["listing_pages"] += 1
            links = [link for link in links if link.source_url not in seen]
            if not links:
                break
            if lane == "detail":
                links = links[:limit]
            summary["discovered"] += len(links)
            for link in links:
                seen.add(link.source_url)
                record = {"url": link.source_url, "listing_price": link.payload.get("price"),
                          "listing_availability": link.payload.get("availability"),
                          "listing_title": link.payload.get("title_raw") or link.payload.get("title")}
                if not positive_price(record["listing_price"]):
                    summary["errors"].append({"url": link.source_url, "error": "Missing/invalid listing price"})
                if lane == "detail":
                    summary["records"].append(record)
                    html = transport.fetch(link.source_url, "detail")
                    record.update(detail_record(shop, detail, html, link))
                    summary["fetched"] += 1
                    summary["valid_eans" if record["ean"] else "missing_ean"] += 1
                    summary["identity_disagreements"] += int(record["identity_disagreement"])
                else:
                    summary["records"].append(record)
                print("[WINDOWS-BASELINE-RECORD]", json.dumps(record, ensure_ascii=False), flush=True)
    except Exception as exc:
        status = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else None
        match = re.search(r"(?:HTTP |status=)(\d{3})\b", str(exc))
        summary["errors"].append({"error": str(exc), "http_status": status or (int(match.group(1)) if match else None)})
    finally:
        summary["transport"] = transport.events
        transport.close()
    passed = summary["discovered"] > 0 and not summary["errors"]
    if lane == "detail":
        passed = passed and summary["valid_eans"] >= min(3, limit) and not summary["identity_disagreements"]
    summary["status"] = "green" if passed else "red"
    blocked = any(error.get("http_status") in {403, 429} for error in summary["errors"])
    summary["source_access"] = "blocked" if blocked else "available" if summary["discovered"] else "failed"
    path = Path("output/windows-baseline") / f"{shop}-{lane}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    text = (f"### {shop} | Linux | Windows baseline | {lane}: {summary['status']}\n\n"
            f"Source `{manifest['commit'][:7]}`. Listing pages: {summary['listing_pages']}; "
            f"records: {summary['discovered']}; details: {summary['fetched']}; "
            f"validated GTINs: {summary['valid_eans']}; EAN disagreements: {summary['identity_disagreements']}; "
            f"errors: {len(summary['errors'])}. Database writes: 0.\n\n"
            + "\n".join(f"- {error['error']}" for error in summary["errors"]) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write(text)
    print("[WINDOWS-BASELINE-SUMMARY]", json.dumps({k: v for k, v in summary.items() if k != "records"}), flush=True)
    return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop", required=True, choices=SHOPS)
    parser.add_argument("--lane", required=True, choices=("price", "detail"))
    parser.add_argument("--limit", required=True, type=int)
    args = parser.parse_args(argv)
    maximum = 3 if args.lane == "price" else 25
    if not 1 <= args.limit <= maximum:
        parser.error(f"{args.lane} baseline limit must be 1..{maximum}")
    return run(args.shop, args.lane, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
