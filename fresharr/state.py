import json
import logging
import os
import tempfile
import time

log = logging.getLogger(__name__)

# Item statuses
ADDED = "added"          # successfully sent to Radarr/Sonarr
EXISTS = "exists"        # already present in the *arr library
NOT_FOUND = "not_found"  # lookup returned no usable match (retried after a delay)
FAILED = "failed"        # add attempt errored (retried on every run)


class State:
    """Persistent record of items Fresharr has already handled, so restarts
    and repeated runs don't re-add or re-look-up the same titles forever."""

    def __init__(self, path: str, retry_not_found_days: int = 7):
        self.path = path
        self.retry_not_found_seconds = retry_not_found_days * 86400
        self._items: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            self._items = data.get("items", {})
        except FileNotFoundError:
            self._items = {}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read state file %s (%s); starting fresh", self.path, exc)
            self._items = {}

    def save(self) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "items": self._items}, fh, indent=2, sort_keys=True)
            os.replace(tmp_path, self.path)
        except OSError:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def record(self, key: str, status: str, title: str, kind: str | None = None) -> None:
        entry = {"status": status, "title": title, "at": int(time.time())}
        if kind:
            entry["kind"] = kind
        self._items[key] = entry

    def should_skip(self, key: str) -> bool:
        entry = self._items.get(key)
        if not entry:
            return False
        status = entry.get("status")
        if status in (ADDED, EXISTS):
            return True
        if status == NOT_FOUND:
            age = time.time() - entry.get("at", 0)
            return age < self.retry_not_found_seconds
        return False  # FAILED and anything unknown: retry

    def entries(self) -> dict[str, dict]:
        return dict(self._items)

    def __len__(self) -> int:
        return len(self._items)
