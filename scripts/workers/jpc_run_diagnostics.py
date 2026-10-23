"""Publish bounded, credential-free JPC run counts as a GitHub annotation."""
from __future__ import annotations

import ast
import json
from pathlib import Path


def report(directory: Path) -> dict:
    result = {"worker": "jpc", "summary_available": False, "shards": []}
    summary_path = directory / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        result["summary_available"] = True
        for key in ("status", "observations", "priced_products", "source_returncode",
                    "database_writes", "source_quarantine_count"):
            result[key] = summary.get(key)
        result["error_count"] = summary.get("error_count")
        # Never copy exception messages, connection strings or product payloads.
    for index in range(4):
        path = directory / f"jpc-source-shard-{index}.log"
        shard = {"index": index, "log_available": path.exists(), "pages": 0,
                 "last_page": None, "http_errors": [], "network_error": False,
                 "duplicate_stops": 0}
        if path.exists():
            statuses = set()
            for line in path.read_text(errors="replace").splitlines():
                if line.startswith("[JPC-DISCOVER-ERROR]"):
                    shard["network_error"] = True
                if line.startswith("[JPC-DISCOVER-RATE-LIMIT]"):
                    statuses.add(429)
                for marker in ("[JPC-DISCOVER-PAGE]", "[JPC-DISCOVER-HTTP-SKIP]", "[JPC-DISCOVER-STOP]"):
                    if not line.startswith(marker):
                        continue
                    try:
                        data = ast.literal_eval(line[len(marker):].strip())
                    except (ValueError, SyntaxError):
                        continue
                    if not isinstance(data, dict):
                        continue
                    if marker == "[JPC-DISCOVER-PAGE]":
                        shard["pages"] += 1
                        if isinstance(data.get("page"), int):
                            shard["last_page"] = data["page"]
                    elif marker == "[JPC-DISCOVER-STOP]":
                        shard["duplicate_stops"] += int(data.get("reason") == "duplicate_page_signature")
                    elif isinstance(data.get("status_code"), int):
                        statuses.add(data["status_code"])
            shard["http_errors"] = sorted(statuses)
        result["shards"].append(shard)
    return result


def main():
    result = report(Path("output/price-verification/jpc"))
    message = json.dumps(result, separators=(",", ":"))
    # Workflow command escaping; report contains only counts, flags and status.
    message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print("::notice title=JPC price diagnosis::" + message, flush=True)


if __name__ == "__main__":
    main()
