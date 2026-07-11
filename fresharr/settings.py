"""User-adjustable settings managed through the web interface.

Unlike Config (environment variables, fixed at container start), these
live in /config/settings.json, are edited from the web UI, and take
effect without a restart. Scheduling and per-source enablement live
here by design: the run interval and which sites get scraped should be
changed in the UI, not by recreating the container.
"""

import json
import logging
import os
import tempfile
import threading

log = logging.getLogger(__name__)

MIN_INTERVAL_DAYS = 1.0  # never poll discovery sites more than daily


class SettingsError(ValueError):
    pass


class SettingsStore:
    def __init__(self, path: str, source_defaults: dict[str, bool],
                 default_interval_days: float = 1.0):
        self.path = path
        self._source_defaults = dict(source_defaults)
        self._default_interval = max(MIN_INTERVAL_DAYS, default_interval_days)
        self._lock = threading.Lock()
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                self._data = json.load(fh)
        except FileNotFoundError:
            self._data = {}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read settings file %s (%s); using defaults",
                        self.path, exc)
            self._data = {}

    def _save(self) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".settings-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, **self._data}, fh, indent=2, sort_keys=True)
            os.replace(tmp_path, self.path)
        except OSError:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    @property
    def run_interval_days(self) -> float:
        with self._lock:
            raw = self._data.get("run_interval_days", self._default_interval)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return self._default_interval
        return max(MIN_INTERVAL_DAYS, value)

    def is_enabled(self, source_name: str) -> bool:
        default = self._source_defaults.get(source_name, False)
        with self._lock:
            entry = self._data.get("sources", {}).get(source_name, {})
        enabled = entry.get("enabled")
        return default if enabled is None else bool(enabled)

    def snapshot(self) -> dict:
        return {
            "run_interval_days": self.run_interval_days,
            "sources": {name: {"enabled": self.is_enabled(name)}
                        for name in self._source_defaults},
        }

    def update(self, payload: dict) -> dict:
        """Apply a partial update from the web UI and persist it.

        Accepts {"run_interval_days": <number>, "sources": {"<name>":
        {"enabled": <bool>}}}; either part may be omitted. Intervals below
        the daily minimum are clamped, unknown sources are rejected.
        """
        if not isinstance(payload, dict):
            raise SettingsError("Expected a JSON object")

        changes: dict = {}
        if "run_interval_days" in payload:
            try:
                interval = float(payload["run_interval_days"])
            except (TypeError, ValueError):
                raise SettingsError("run_interval_days must be a number")
            if interval < MIN_INTERVAL_DAYS:
                log.info("Requested interval %.2f days is below the daily minimum; "
                         "clamping to 1", interval)
                interval = MIN_INTERVAL_DAYS
            changes["run_interval_days"] = interval

        if "sources" in payload:
            sources = payload["sources"]
            if not isinstance(sources, dict):
                raise SettingsError("sources must be an object")
            for name, entry in sources.items():
                if name not in self._source_defaults:
                    raise SettingsError(f"Unknown source: {name}")
                if not isinstance(entry, dict) or not isinstance(entry.get("enabled"), bool):
                    raise SettingsError(f"sources.{name} must be {{\"enabled\": true|false}}")
            changes["sources"] = sources

        with self._lock:
            if "run_interval_days" in changes:
                self._data["run_interval_days"] = changes["run_interval_days"]
            for name, entry in changes.get("sources", {}).items():
                self._data.setdefault("sources", {}).setdefault(name, {})["enabled"] = \
                    entry["enabled"]
            self._save()
        return self.snapshot()
