"""User-adjustable settings managed through the web interface.

Unlike Config (environment variables, fixed at container start), these
live in /config/settings.json, are edited from the web UI, and take
effect without a restart. The run interval here is a target cadence,
not an exact timer: the scheduler adds random jitter around it (with a
hard minimum of 18 hours between runs) so Fresharr never hits the
discovery sites at one predictable time of day.
"""

import dataclasses
import json
import logging
import os
import re
import tempfile
import threading

log = logging.getLogger(__name__)

MIN_INTERVAL_DAYS = 1.0  # never target more than a daily cadence

_LANG_CODE_RE = re.compile(r"^[a-z]{2,3}$")


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

    def _language_list(self, key: str) -> list[str]:
        with self._lock:
            raw = self._data.get(key, [])
        if not isinstance(raw, list):
            return []
        return [lang for lang in raw
                if isinstance(lang, str) and _LANG_CODE_RE.match(lang)]

    @property
    def languages(self) -> list[str]:
        """Original-language codes for movies & TV; empty means all."""
        return self._language_list("languages")

    @property
    def anime_languages(self) -> list[str]:
        """Original-language codes for anime; empty means all."""
        return self._language_list("anime_languages")

    def options(self) -> dict:
        """UI-set option overrides (Config attribute name -> value)."""
        with self._lock:
            raw = self._data.get("options", {})
        return dict(raw) if isinstance(raw, dict) else {}

    def apply_to(self, config):
        """Return a copy of an env-based Config with the UI-set option
        overrides applied. Called at the start of every run (and by the web
        layer), so UI changes take effect without a restart."""
        from .options import OPTIONS_BY_KEY

        effective = dataclasses.replace(config)
        for key, value in self.options().items():
            defn = OPTIONS_BY_KEY.get(key)
            if defn is None:
                continue
            if defn.is_list:
                value = [part.strip() for part in str(value).split(",")
                         if part.strip()]
            setattr(effective, key, value)
        return effective

    def snapshot(self) -> dict:
        return {
            "run_interval_days": self.run_interval_days,
            "sources": {name: {"enabled": self.is_enabled(name)}
                        for name in self._source_defaults},
            "languages": self.languages,
            "anime_languages": self.anime_languages,
            "options": self.options(),
        }

    def update(self, payload: dict) -> dict:
        """Apply a partial update from the web UI and persist it.

        Accepts {"run_interval_days": <number>, "sources": {"<name>":
        {"enabled": <bool>}}, "languages": [...], "anime_languages": [...]};
        any part may be omitted. Intervals below the daily minimum are
        clamped, unknown sources and malformed language codes are rejected.
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

        for key in ("languages", "anime_languages"):
            if key not in payload:
                continue
            languages = payload[key]
            if not isinstance(languages, list):
                raise SettingsError(f"{key} must be a list of language codes")
            for lang in languages:
                if not isinstance(lang, str) or not _LANG_CODE_RE.match(lang):
                    raise SettingsError(
                        f"Invalid language code: {lang!r} (expected e.g. 'en', 'ja')")
            changes[key] = sorted(set(languages))

        if "options" in payload:
            from .options import OPTIONS_BY_KEY, validate_option
            submitted = payload["options"]
            if not isinstance(submitted, dict):
                raise SettingsError("options must be an object")
            normalized = {}
            for key, value in submitted.items():
                defn = OPTIONS_BY_KEY.get(key)
                if defn is None:
                    raise SettingsError(f"Unknown option: {key}")
                normalized[key] = validate_option(defn, value)
            changes["options"] = normalized

        with self._lock:
            if "run_interval_days" in changes:
                self._data["run_interval_days"] = changes["run_interval_days"]
            for name, entry in changes.get("sources", {}).items():
                self._data.setdefault("sources", {}).setdefault(name, {})["enabled"] = \
                    entry["enabled"]
            for key in ("languages", "anime_languages"):
                if key in changes:
                    self._data[key] = changes[key]
            for key, value in changes.get("options", {}).items():
                if value is None:  # cleared in the UI: fall back to env/default
                    self._data.get("options", {}).pop(key, None)
                else:
                    self._data.setdefault("options", {})[key] = value
            self._save()
        return self.snapshot()
