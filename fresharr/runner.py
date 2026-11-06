import logging
import time

import requests

from . import state as state_mod
from .arr.base import ArrError
from .arr.radarr import Radarr
from .arr.sonarr import Sonarr
from .config import Config
from .filters import Rules, normalize_language, rules_for
from .models import MOVIE, TV, MediaItem
from .settings import SettingsStore
from .sources import build_sources
from .state import State
from .status import load_status, save_status

log = logging.getLogger(__name__)


def _rules_by_kind(settings: SettingsStore) -> dict[str, Rules]:
    """The language/genre/network filters for movies, TV and anime."""
    return {kind: rules_for(settings, kind) for kind in ("movie", "tv", "anime")}


def _source_reason(item: MediaItem, rules: Rules) -> str | None:
    """Why the discovery site's own data already rules a title out. Unknown
    language, genres or network always pass; Radarr/Sonarr's metadata is
    checked again at add time."""
    language = normalize_language(item.language)
    if rules.languages and language and language not in rules.languages:
        return f"language {item.language}"
    return rules.genre_reason(item.genres) or rules.network_reason(item.network)


def collect_items(config: Config, settings: SettingsStore) -> list[MediaItem]:
    items: list[MediaItem] = []
    for source in build_sources(config, settings):
        try:
            items.extend(source.fetch())
        except Exception:
            log.exception("Source %r failed; continuing with other sources", source.name)

    # Global filters
    if config.min_year:
        items = [i for i in items if i.year is None or i.year >= config.min_year]
    if not config.radarr_enabled:
        items = [i for i in items if i.media_type != MOVIE]
    if not config.sonarr_enabled:
        items = [i for i in items if i.media_type != TV]

    # Language, genre and network filters (web UI settings), kept separately
    # for movies, TV shows and anime.
    rules = _rules_by_kind(settings)
    if any(r.active for r in rules.values()):
        before = len(items)
        items = [i for i in items if not _source_reason(i, rules[i.content_kind])]
        if before != len(items):
            log.info("Language/genre/network filters: %d of %d candidates kept",
                     len(items), before)

    # Dedupe across sources/lists, keeping the first occurrence but preferring
    # any duplicate that carries a TMDB id (exact matching downstream).
    by_key: dict[str, MediaItem] = {}
    for item in items:
        existing = by_key.get(item.key)
        if existing is None or (existing.tmdb_id is None and item.tmdb_id is not None):
            by_key[item.key] = item
    return list(by_key.values())


def run_once(config: Config, settings: SettingsStore) -> dict:
    started = time.time()
    config = settings.apply_to(config)  # web-UI options override env defaults
    enabled = [name for name, entry in settings.snapshot()["sources"].items()
               if entry["enabled"]]
    log.info("Starting discovery run (sources: %s, dry_run: %s)",
             ", ".join(enabled) or "none", config.dry_run)
    items = collect_items(config, settings)
    log.info("%d unique candidates after filtering", len(items))

    counts = {"added": 0, "exists": 0, "not_found": 0, "failed": 0,
              "skipped": 0, "would_add": 0, "filtered": 0}
    added_titles: list[str] = []
    error: str | None = None

    state = State(config.state_file, config.retry_not_found_days)
    rules = _rules_by_kind(settings)
    signatures = {kind: r.signature() for kind, r in rules.items()}
    clients: dict[str, Radarr | Sonarr] = {}
    if config.radarr_enabled:
        clients[MOVIE] = Radarr(config)
    if config.sonarr_enabled:
        clients[TV] = Sonarr(config)
    if not clients:
        error = ("Neither Radarr nor Sonarr is configured - add a connection "
                 "in the web interface")
        log.error("%s", error)

    # Verify each *arr is reachable up front. One that can't be reached is
    # taken out of service for this run and its items deferred to the next run.
    # Duplicate detection uses each lookup result's library id, so there's no
    # need to fetch the (potentially huge) library first.
    deferred: dict[str, str] = {}   # media_type -> reason its items were skipped
    for media_type, client in clients.items():
        try:
            client.check_connection()
        except (ArrError, requests.RequestException) as exc:
            log.error("%s is not responding; deferring its items to the next "
                      "run: %s", client.app_name, exc)
            deferred[media_type] = f"{client.app_name} not responding: {exc}"
    if clients and len(deferred) == len(clients) and error is None:
        error = "; ".join(dict.fromkeys(deferred.values()))

    if error is None:
        # If an *arr stops responding mid-run, stop sending to it after this
        # many consecutive failures and defer the rest to the next run.
        FAILURE_LIMIT = 3
        consecutive_failures = {media_type: 0 for media_type in clients}
        for item in items:
            if item.media_type in deferred:
                counts["skipped"] += 1
                continue
            if state.should_skip(item.key, signatures[item.content_kind]):
                counts["skipped"] += 1
                continue
            if counts["added"] >= config.max_items_per_run:
                log.info("Reached MAX_ITEMS_PER_RUN=%d; remaining candidates wait "
                         "for the next run", config.max_items_per_run)
                break
            client = clients[item.media_type]
            if config.dry_run:
                log.info("[dry run] would add %s", item.describe())
                counts["would_add"] += 1
                continue
            try:
                status = client.add(item, rules[item.content_kind])
                consecutive_failures[item.media_type] = 0
            except ArrError as exc:
                log.error("Configuration problem adding %s: %s", item.describe(), exc)
                status = state_mod.FAILED
            except requests.RequestException as exc:
                log.warning("Failed to add %s: %s", item.describe(), exc)
                status = state_mod.FAILED
                consecutive_failures[item.media_type] += 1
                if consecutive_failures[item.media_type] >= FAILURE_LIMIT:
                    reason = (f"{client.app_name} stopped responding after "
                              f"{FAILURE_LIMIT} consecutive failures; deferring "
                              f"the rest to the next run")
                    log.error("%s", reason)
                    deferred[item.media_type] = reason
            state.record(item.key, status, item.title, item.content_kind,
                         signatures[item.content_kind])
            counts[status] = counts.get(status, 0) + 1
            if status == state_mod.ADDED:
                added_titles.append(item.title)

        if not config.dry_run:
            state.save()
        # Surface a partial outage (one *arr down, the other fine) in the UI.
        if deferred and error is None:
            error = "; ".join(dict.fromkeys(deferred.values()))
        log.info(
            "Run complete: %d added, %d already in library, %d not found, "
            "%d filtered, %d failed, %d previously handled%s",
            counts["added"], counts["exists"], counts["not_found"],
            counts["filtered"], counts["failed"], counts["skipped"],
            f", {counts['would_add']} would be added (dry run)" if config.dry_run else "",
        )

    summary = {
        "last_run_at": int(started),
        "duration_seconds": round(time.time() - started, 1),
        "sources": enabled,
        "candidates": len(items),
        "counts": counts,
        "added_titles": added_titles,
        "dry_run": config.dry_run,
        "error": error,
    }
    try:
        existing = load_status(config.status_file)
        existing.update(summary)
        save_status(config.status_file, existing)
    except OSError as exc:
        log.warning("Could not persist run status: %s", exc)
    return summary
