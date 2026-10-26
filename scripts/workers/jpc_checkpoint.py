"""Small CAS checkpoint on a dedicated branch; product evidence stays in artifacts."""
from __future__ import annotations

import base64
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BRANCH = 'jpc-price-progress'
PATH = 'state/jpc-price/checkpoint.json'


class GitHubCheckpoint:
    def __init__(self):
        self.repo = os.environ['GITHUB_REPOSITORY']
        self.token = os.environ['GH_TOKEN']
        self.sha = None
        self.branch_exists = False

    def api(self, method, path, body=None):
        request = Request('https://api.github.com/repos/'+self.repo+'/'+path,
            method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer '+self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'User-Agent': 'curedplant-jpc-checkpoint'})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def load(self):
        try:
            data = self.api('GET', 'contents/'+PATH+'?ref='+BRANCH)
        except HTTPError as error:
            if error.code != 404:
                raise
            return None
        self.sha = data['sha']
        self.branch_exists = True
        if data.get('encoding') != 'base64':
            raise ValueError('Checkpoint exceeds expected compact size')
        return json.loads(base64.b64decode(data['content']))

    def save(self, state):
        if not self.branch_exists:
            try:
                self.api('GET', 'git/ref/heads/'+BRANCH)
            except HTTPError as error:
                if error.code != 404:
                    raise
                head = self.api('GET', 'git/ref/heads/main')['object']['sha']
                self.api('POST', 'git/refs', {'ref': 'refs/heads/'+BRANCH, 'sha': head})
            self.branch_exists = True
        body = {'message': 'Checkpoint bounded JPC price cycle', 'branch': BRANCH,
                'content': base64.b64encode(json.dumps(state, separators=(',', ':')).encode()).decode()}
        if self.sha:
            body['sha'] = self.sha
        # A conflict stops the worker. Never overwrite a newer cursor or force-push.
        result = self.api('PUT', 'contents/'+PATH, body)
        self.sha = result['content']['sha']
