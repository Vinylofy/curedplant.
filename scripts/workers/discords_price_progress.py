"""Durable page cursor for bounded Discords price runs."""
from __future__ import annotations

import base64
import json
import os
import subprocess


BRANCH = "automation/discords-price-progress"
MAX_PAGE = 250


def initial_state():
    return {"version": 1, "shop": "discords", "next_page": 1, "last_run_id": None}


def _api(method, endpoint, payload=None):
    command = ["gh", "api", "--method", method, endpoint]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "GitHub progress API failed")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def validate(state):
    if state.get("version") != 1 or state.get("shop") != "discords":
        raise ValueError("Discords price checkpoint has an unsupported version or shop")
    page = state.get("next_page")
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= MAX_PAGE:
        raise ValueError("Discords price checkpoint has an invalid next_page")
    return state


class GitHubProgress:
    """Keep a tiny cursor on its own branch; never reset a corrupt checkpoint."""
    def __init__(self):
        self.sha = None
        self.repository = os.environ.get("GITHUB_REPOSITORY", "Vinylofy/curedplant.")
        self.path = f"repos/{self.repository}/contents/.state/prices/discords.json"

    def load(self):
        endpoint = self.path + "?ref=" + BRANCH
        try:
            data = _api("GET", endpoint)
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            self.sha = None
            return initial_state()
        self.sha = data["sha"]
        return validate(json.loads(base64.b64decode(data["content"])))

    def _ensure_branch(self):
        try:
            _api("GET", f"repos/{self.repository}/git/ref/heads/{BRANCH}")
            return
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
        main = _api("GET", f"repos/{self.repository}/git/ref/heads/main")
        try:
            _api("POST", f"repos/{self.repository}/git/refs", {
                "ref": f"refs/heads/{BRANCH}", "sha": main["object"]["sha"]})
        except RuntimeError as exc:
            # Another shop's first writer may have created the shared branch.
            if "HTTP 422" not in str(exc):
                raise
            _api("GET", f"repos/{self.repository}/git/ref/heads/{BRANCH}")

    def save(self, state):
        validate(state)
        self._ensure_branch()
        payload = {"message": "Discords price progress [skip ci]", "branch": BRANCH,
                   "content": base64.b64encode((json.dumps(state, indent=2) + "\n").encode()).decode()}
        if self.sha:
            payload["sha"] = self.sha
        result = _api("PUT", self.path, payload)
        self.sha = result["content"]["sha"]
