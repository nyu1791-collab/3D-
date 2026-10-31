"""Remember used articles and published episodes.

Local runs keep a JSON file in the data folder. In Actions the same JSON lives in
a private repository variable (ZUNDA_STATE), so the public repository never shows
the history and nothing has to be committed.
"""

import json
import os
import time
import urllib.parse
from pathlib import Path

from . import http

SEEN_TTL = 45 * 86400
EPISODES = 60
MAX_BYTES = 46_000


class FileBackend:
    def __init__(self, path):
        self.path = Path(path).expanduser()

    def read(self):
        return self.path.read_text(encoding="utf-8") if self.path.is_file() else None

    def write(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self.path)


class VariableBackend:
    def __init__(self, repository, token, name="ZUNDA_STATE", request=http.request):
        if not repository or not token:
            raise RuntimeError("ZUNDA_GITHUB_TOKEN と GITHUB_REPOSITORY が必要です")
        self.url = f"https://api.github.com/repos/{repository}/actions/variables"
        self.name = name
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        self.request = request

    def read(self):
        try:
            return self.request("GET", f"{self.url}/{urllib.parse.quote(self.name)}", headers=self.headers).json().get("value")
        except http.HttpError as error:
            if error.status == 404:
                return None
            raise

    def write(self, text):
        body = {"name": self.name, "value": text}
        try:
            self.request("PATCH", f"{self.url}/{urllib.parse.quote(self.name)}", headers=self.headers, json_body=body)
        except http.HttpError as error:
            if error.status != 404:
                raise
            self.request("POST", self.url, headers=self.headers, json_body=body)


def backend_from_env(data_dir):
    if os.environ.get("ZUNDA_STATE_BACKEND") == "variable":
        return VariableBackend(os.environ.get("GITHUB_REPOSITORY"), os.environ.get("ZUNDA_GITHUB_TOKEN"))
    return FileBackend(Path(data_dir) / "zunda-state.json")


class Store:
    def __init__(self, backend, clock=time.time):
        self.backend = backend
        self.clock = clock

    def load(self):
        text = self.backend.read()
        data = json.loads(text) if text else {}
        data.setdefault("seen", {})
        data.setdefault("episodes", [])
        return data

    def save(self, data):
        now = self.clock()
        data["seen"] = {u: t for u, t in data["seen"].items() if now - t < SEEN_TTL}
        data["episodes"] = data["episodes"][-EPISODES:]
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        while len(text.encode()) > MAX_BYTES and data["seen"]:
            oldest = min(data["seen"], key=data["seen"].get)
            del data["seen"][oldest]
            text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        self.backend.write(text)
