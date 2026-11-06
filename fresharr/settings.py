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
_CARD_ID_RE = re.compile(r"^[a-z0-9-]{1,40}$")
_CARD_LAYOUT_KEYS = ("1", "2", "3")
# Generous next to the handful of real cards, but bounded so a malformed or
# hostile request can't persist an unbounded layout into settings.json.
_MAX_CARDS_PER_LAYOUT = 64
_MAX_FILTER_ENTRIES = 50

# Rating thresholds that were a single knob before movies and TV got their
# own: a legacy value seeds both new keys so saved settings keep working.
_SPLIT_OPTION_MIGRATIONS = {
    "metacritic_min_score": ("metacritic_min_score_movies", "metacritic_min_score_tv"),
    "tmdb_min_rating": ("tmdb_min_rating_movies", "tmdb_min_rating_tv"),
    "trakt_min_rating": ("trakt_min_rating_movies", "trakt_min_rating_tv"),
}


class SettingsError(ValueError):
    pass


def _clean_one_layout(cols, n: int) -> list | None:
    """Validate a single card layout (a list of n columns of card ids).

    Returns a sanitised copy (ids deduplicated across the whole layout) or
    None if the structure is not n columns of well-formed ids.
    """
    if not isinstance(cols, list) or len(cols) != n:
        return None
    seen: set[str] = set()
    out: list[list[str]] = []
    for col in cols:
        if not isinstance(col, list):
            return None
        col_ids: list[str] = []
        for card_id in col:
            if len(seen) >= _MAX_CARDS_PER_LAYOUT:
                break
            if (isinstance(card_id, str) and _CARD_ID_RE.match(card_id)
                    and card_id not in seen):
                seen.add(card_id)
                col_ids.append(card_id)
        out.append(col_ids)
    return out if seen else None


def _valid_name(entry, known_ids) -> bool:
    """A built-in network/studio id, or a name typed in for one not listed."""
    from .filters import CUSTOM_NETWORK_RE
    return isinstance(entry, str) and (
        entry in known_ids or bool(CUSTOM_NETWORK_RE.match(entry.strip())))


def _valid_network(entry) -> bool:
    from .filters import NETWORK_IDS
    return _valid_name(entry, NETWORK_IDS)


def _valid_studio(entry) -> bool:
    from .filters import STUDIO_IDS
    return _valid_name(entry, STUDIO_IDS)


def _clean_include_exclude(value, kinds, label: str, valid, normalise) -> dict:
    """Validate a partial {kind: {"include": [...], "exclude": [...]}} update.
    A request that puts one value on both sides is rejected rather than
    guessed at."""
    if not isinstance(value, dict):
        raise SettingsError(f"{label} must be an object")
    out: dict = {}
    for kind, entry in value.items():
        if kind not in kinds:
            raise SettingsError(f"{label} kinds are {', '.join(kinds)} (got {kind!r})")
        if not isinstance(entry, dict) or not set(entry) <= {"include", "exclude"}:
            raise SettingsError(f"{label}.{kind} must be {{\"include\": [...], "
                                f"\"exclude\": [...]}}")
        cleaned = {}
        for side, items in entry.items():
            if not isinstance(items, list) or len(items) > _MAX_FILTER_ENTRIES:
                raise SettingsError(
                    f"{label}.{kind}.{side} must be a list of at most "
                    f"{_MAX_FILTER_ENTRIES} entries")
            for item in items:
                if not valid(item):
                    raise SettingsError(f"Unknown {label[:-8]} in {kind}: {item!r}")
            cleaned[side] = sorted({normalise(i) for i in items})
        both = set(cleaned.get("include", ())) & set(cleaned.get("exclude", ()))
        if both:
            raise SettingsError(f"{', '.join(sorted(both))} can't be both included "
                                f"and excluded")
        out[kind] = cleaned
    return out


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
        self._migrate_split_options()

    def _migrate_split_options(self) -> None:
        options = self._data.get("options")
        if not isinstance(options, dict):
            return
        for legacy, (movies_key, tv_key) in _SPLIT_OPTION_MIGRATIONS.items():
            if legacy not in options:
                continue
            value = options.pop(legacy)
            options.setdefault(movies_key, value)
            options.setdefault(tv_key, value)

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

    def _language_list(self, key: str, legacy_key: str | None = None) -> list[str]:
        with self._lock:
            if key in self._data:
                raw = self._data[key]
            elif legacy_key and legacy_key in self._data:
                raw = self._data[legacy_key]  # pre-split settings files
            else:
                raw = []
        if not isinstance(raw, list):
            return []
        return [lang for lang in raw
                if isinstance(lang, str) and _LANG_CODE_RE.match(lang)]

    @property
    def movie_languages(self) -> list[str]:
        """Original-language codes for movies; empty means all."""
        return self._language_list("movie_languages", legacy_key="languages")

    @property
    def tv_languages(self) -> list[str]:
        """Original-language codes for TV shows; empty means all."""
        return self._language_list("tv_languages", legacy_key="languages")

    @property
    def anime_languages(self) -> list[str]:
        """Original-language codes for anime; empty means all."""
        return self._language_list("anime_languages")

    def _include_exclude(self, key: str, kinds, clean) -> dict:
        with self._lock:
            raw = self._data.get(key, {})
        out = {}
        for kind in kinds:
            entry = raw.get(kind) if isinstance(raw, dict) else None
            entry = entry if isinstance(entry, dict) else {}
            out[kind] = {side: clean(entry.get(side)) for side in ("include", "exclude")}
        return out

    @property
    def genre_filters(self) -> dict:
        """{"movie"|"tv"|"anime": {"include": [ids], "exclude": [ids]}}.
        Empty include means any genre."""
        from .filters import GENRE_IDS, GENRE_KINDS
        return self._include_exclude(
            "genre_filters", GENRE_KINDS,
            lambda v: [g for g in v if g in GENRE_IDS] if isinstance(v, list) else [])

    @property
    def network_filters(self) -> dict:
        """{"tv"|"anime": {"include": [...], "exclude": [...]}}: known network
        ids, or names typed in for ones not in the list."""
        from .filters import NETWORK_KINDS
        return self._include_exclude(
            "network_filters", NETWORK_KINDS,
            lambda v: [n for n in v if _valid_network(n)] if isinstance(v, list) else [])

    @property
    def studio_filters(self) -> dict:
        """{"movie": {"include": [...], "exclude": [...]}}: known studio ids,
        or names typed in for ones not in the list."""
        from .filters import STUDIO_KINDS
        return self._include_exclude(
            "studio_filters", STUDIO_KINDS,
            lambda v: [n for n in v if _valid_studio(n)] if isinstance(v, list) else [])

    def options(self) -> dict:
        """UI-set option overrides (Config attribute name -> value)."""
        with self._lock:
            raw = self._data.get("options", {})
        return dict(raw) if isinstance(raw, dict) else {}

    @property
    def card_layout(self) -> dict:
        """Per-width dashboard card arrangement, keyed by column count
        ("1"/"2"/"3"). Each value is that many columns of card ids. Widths the
        user has not customised are absent (the UI falls back to its default)."""
        with self._lock:
            raw = self._data.get("card_layout", {})
        if not isinstance(raw, dict):
            return {}
        cleaned = {}
        for key in _CARD_LAYOUT_KEYS:
            if key in raw:
                one = _clean_one_layout(raw[key], int(key))
                if one:
                    cleaned[key] = one
        return cleaned

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
            "movie_languages": self.movie_languages,
            "tv_languages": self.tv_languages,
            "anime_languages": self.anime_languages,
            "genre_filters": self.genre_filters,
            "network_filters": self.network_filters,
            "studio_filters": self.studio_filters,
            "options": self.options(),
            "card_layout": self.card_layout,
        }

    def update(self, payload: dict) -> dict:
        """Apply a partial update from the web UI and persist it.

        Accepts {"run_interval_days": <number>, "sources": {"<name>":
        {"enabled": <bool>}}, "movie_languages": [...], "tv_languages": [...],
        "anime_languages": [...], "genre_filters": {...}, "network_filters": {...},
        "studio_filters": {...}, "options": {...}}; any part may be omitted.
        Intervals below the daily minimum are clamped, unknown sources and
        malformed language codes are rejected.
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

        for key in ("movie_languages", "tv_languages", "anime_languages"):
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

        if "genre_filters" in payload:
            from .filters import GENRE_IDS, GENRE_KINDS
            changes["genre_filters"] = _clean_include_exclude(
                payload["genre_filters"], GENRE_KINDS, "genre_filters",
                lambda g: isinstance(g, str) and g in GENRE_IDS, lambda g: g)

        if "network_filters" in payload:
            from .filters import NETWORK_KINDS
            changes["network_filters"] = _clean_include_exclude(
                payload["network_filters"], NETWORK_KINDS, "network_filters",
                _valid_network, lambda n: n.strip())

        if "studio_filters" in payload:
            from .filters import STUDIO_KINDS
            changes["studio_filters"] = _clean_include_exclude(
                payload["studio_filters"], STUDIO_KINDS, "studio_filters",
                _valid_studio, lambda n: n.strip())

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

        if "card_layout" in payload:
            layout = payload["card_layout"]
            if not isinstance(layout, dict):
                raise SettingsError("card_layout must be an object")
            normalized_layout: dict = {}
            for key, cols in layout.items():
                if key not in _CARD_LAYOUT_KEYS:
                    raise SettingsError(
                        f"card_layout keys must be 1, 2 or 3 (got {key!r})")
                if cols is None:               # reset this width to its default
                    normalized_layout[key] = None
                    continue
                one = _clean_one_layout(cols, int(key))
                if one is None:
                    raise SettingsError(
                        f"card_layout[{key}] must be {key} column(s) of card ids")
                normalized_layout[key] = one
            changes["card_layout"] = normalized_layout

        with self._lock:
            if "run_interval_days" in changes:
                self._data["run_interval_days"] = changes["run_interval_days"]
            for name, entry in changes.get("sources", {}).items():
                self._data.setdefault("sources", {}).setdefault(name, {})["enabled"] = \
                    entry["enabled"]
            for key in ("movie_languages", "tv_languages", "anime_languages"):
                if key in changes:
                    self._data[key] = changes[key]
            for key in ("genre_filters", "network_filters", "studio_filters"):
                for kind, entry in changes.get(key, {}).items():
                    store = self._data.get(key)
                    if not isinstance(store, dict):
                        store = self._data[key] = {}
                    current = store.get(kind) if isinstance(store.get(kind), dict) else {}
                    # Moving a value to one side takes it off the other.
                    for side, values in entry.items():
                        other = "exclude" if side == "include" else "include"
                        if other not in entry:
                            current[other] = [v for v in current.get(other, [])
                                              if v not in values]
                        current[side] = values
                    store[kind] = current
            for key, value in changes.get("options", {}).items():
                if value is None:  # cleared in the UI: fall back to env/default
                    self._data.get("options", {}).pop(key, None)
                else:
                    self._data.setdefault("options", {})[key] = value
            if "card_layout" in changes:
                store = self._data.get("card_layout")
                if not isinstance(store, dict):
                    store = {}
                for key, value in changes["card_layout"].items():
                    if value is None:      # reset: drop the saved width
                        store.pop(key, None)
                    else:
                        store[key] = value
                if store:
                    self._data["card_layout"] = store
                else:
                    self._data.pop("card_layout", None)
            self._save()
        return self.snapshot()
