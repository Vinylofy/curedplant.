"""Read immutable evidence from a reviewed dry-run, without contacting a shop."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


def load_approved_source(directory, worker, limit, run_id, *, now=None):
    root = Path(directory) / worker
    summary = json.loads((root / "summary.json").read_text())
    if (summary.get("worker") != worker or str(summary.get("run_id")) != str(run_id)
            or summary.get("limit") != limit or summary.get("write") is not False
            or summary.get("database_writes") != 0 or summary.get("status") != "green"
            or summary.get("source_returncode") != 0 or summary.get("errors")):
        raise ValueError("Approved source must be a successful, matching, write=false run with zero database writes")
    started = datetime.fromisoformat(summary["started_at"].replace("Z", "+00:00"))
    now = now or datetime.now(timezone.utc)
    if started.tzinfo is None or not -timedelta(minutes=5) <= now - started <= timedelta(hours=6):
        raise ValueError("Approved source is older than six hours or has an invalid timestamp")
    records = [json.loads(line) for line in (root / "listing-records.jsonl").read_text().splitlines() if line.strip()]
    if not records:
        raise ValueError("Approved source has no listing evidence")
    return records, started
