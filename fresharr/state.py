import logging
import time

from .storage import load_json, save_json

log = logging.getLogger(__name__)

# Item statuses
ADDED = "added"          # successfully sent to Radarr/Sonarr
EXISTS = "exists"        # already present in the *arr library
NOT_FOUND = "not_found"  # lookup returned no usable match (retried after a delay)
FAILED = "failed"        # add attempt errored (retried on every run)
FILTERED = "filtered"    # excluded by a filter, e.g. original language (re-checked after a delay)

# Cap on remembered items so the seen-state file can't grow without bound over
# a long-running install. When exceeded, the oldest entries are dropped; that
# only costs a re-lookup if such a title ever reappears in discovery (the *arr
# still reports it as already in the library), so correctness is unaffected.
MAX_ENTRIES = 10000


class State:
    """Persistent record of items Fresharr has already handled, so restarts
    and repeated runs don't re-add or re-look-up the same titles forever."""

    def __init__(self, path: str, retry_not_found_days: int = 7):
        self.path = path
        self.retry_not_found_seconds = retry_not_found_days * 86400
        self._items: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        data = load_json(self.path, "state")
        items = data.get("items") if isinstance(data, dict) else None
        self._items = items if isinstance(items, dict) else {}

    def _prune(self) -> None:
        """Keep the most-recently-touched entries, drop the oldest."""
        if len(self._items) <= MAX_ENTRIES:
            return
        before = len(self._items)
        kept = sorted(self._items.items(),
                      key=lambda kv: kv[1].get("at", 0), reverse=True)[:MAX_ENTRIES]
        self._items = dict(kept)
        log.info("State file reached %d entries; pruned %d oldest to cap at %d",
                 before, before - MAX_ENTRIES, MAX_ENTRIES)

    def save(self) -> None:
        self._prune()
        save_json(self.path, {"version": 1, "items": self._items},
                  indent=2, sort_keys=True)

    def record(self, key: str, status: str, title: str, kind: str | None = None,
               filters: str | None = None) -> None:
        entry = {"status": status, "title": title, "at": int(time.time())}
        if kind:
            entry["kind"] = kind
        if status == FILTERED and filters:
            entry["filters"] = filters   # fingerprint of the filters that applied
        self._items[key] = entry

    def should_skip(self, key: str, filters: str | None = None) -> bool:
        entry = self._items.get(key)
        if not entry:
            return False
        status = entry.get("status")
        if status in (ADDED, EXISTS):
            return True
        if status == FILTERED and filters and entry.get("filters") != filters:
            return False  # the filters have changed since: look again now
        if status in (NOT_FOUND, FILTERED):
            # Re-check periodically so broadening the language filter later
            # gives these titles another chance, without a lookup every run.
            age = time.time() - entry.get("at", 0)
            return age < self.retry_not_found_seconds
        return False  # FAILED and anything unknown: retry

    def entries(self) -> dict[str, dict]:
        return dict(self._items)

    def __len__(self) -> int:
        return len(self._items)
