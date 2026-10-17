"""Daily EAN budgets and durable catalogue cursors, independent of runner disks."""
from __future__ import annotations

import base64
from datetime import datetime
import json
import os
import subprocess
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

BRANCH = "automation/ean-progress"
DAILY_LIMIT = 100


def day_key(now=None):
    return (now or datetime.now(ZoneInfo("Europe/Amsterdam"))).astimezone(ZoneInfo("Europe/Amsterdam")).date().isoformat()


def initial_state(shop):
    return {"version": 1, "shop": shop, "cursor": {"page": 1, "seed": 0},
            "budget": {"date": "", "reserved": 0}}


def validate_state(state, shop):
    if state.get("version") != 1 or state.get("shop") != shop:
        raise ValueError("Wrong EAN checkpoint version or shop; refusing to reset progress")
    budget, cursor = state["budget"], state["cursor"]
    if not isinstance(budget["reserved"], int) or not 0 <= budget["reserved"] <= DAILY_LIMIT:
        raise ValueError("Invalid daily EAN budget")
    if not isinstance(cursor.get("page"), int) or cursor["page"] < 1 or cursor.get("seed", -1) < 0:
        raise ValueError("Invalid EAN catalogue cursor")
    return state


def reserve(state, requested, today):
    if not 1 <= requested <= DAILY_LIMIT:
        raise ValueError("EAN limit must be 1..100")
    budget = state["budget"]
    if budget["date"] != today:
        budget.update(date=today, reserved=0)
    allocated = min(requested, DAILY_LIMIT - budget["reserved"])
    budget["reserved"] += allocated
    return allocated


class GitHubProgress:
    """A small JSON file per shop on a separate branch, never an Actions cache.

    The workflow supplies GitHub's own token through GH_TOKEN. No token appears
    in command arguments, logs, files, or the checkpoint. A corrupt or forbidden
    checkpoint fails closed instead of silently restarting at page one.
    """
    def __init__(self, shop, repository=None):
        self.shop = shop
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY", "Vinylofy/curedplant.")
        self.path = f"repos/{self.repository}/contents/.state/ean/{shop}.json"
        self.sha = None

    def _api(self, method, path, payload=None):
        command = ["gh", "api", "--method", method, path]
        if payload is not None:
            command += ["--input", "-"]
        result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                                capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "GitHub checkpoint request failed")
        return json.loads(result.stdout)

    def load(self):
        # The dedicated branch is created at rollout. A missing branch/repo is
        # a setup error, not permission to forget previously collected records.
        self._api("GET", f"repos/{self.repository}/git/ref/heads/{BRANCH}")
        try:
            data = self._api("GET", self.path + "?ref=" + quote(BRANCH, safe=""))
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            self.sha = None
            return initial_state(self.shop)
        self.sha = data["sha"]
        return validate_state(json.loads(base64.b64decode(data["content"])), self.shop)

    def save(self, state):
        validate_state(state, self.shop)
        content = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
        payload = {"message": f"EAN progress: {self.shop} [skip ci]", "branch": BRANCH,
                   "content": base64.b64encode(content.encode()).decode()}
        if self.sha:
            payload["sha"] = self.sha
        for attempt in range(3):
            try:
                result = self._api("PUT", self.path, payload)
                self.sha = result["content"]["sha"]
                return
            except RuntimeError as exc:
                if "HTTP 409" not in str(exc) or attempt == 2:
                    raise
                old_sha = self.sha
                self.load()
                if self.sha != old_sha:
                    raise RuntimeError("Another run changed this shop's checkpoint; refusing to overwrite its budget") from exc
                time.sleep(attempt + 1)
