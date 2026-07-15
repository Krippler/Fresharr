import logging
import time

import requests

from . import state as state_mod
from .arr.base import ArrError
from .arr.radarr import Radarr
from .arr.sonarr import Sonarr
from .config import Config
from .models import MOVIE, TV, MediaItem
from .settings import SettingsStore
from .sources import build_sources
from .state import State
from .status import load_status, save_status

log = logging.getLogger(__name__)


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

    # Original-language filters (web UI settings): separate lists for
    # movies, TV shows and anime. Items whose source doesn't report a
    # language always pass - dropping them would silence entire sources
    # like Rotten Tomatoes that carry no language metadata.
    movie_languages = [lang.lower()
                       for lang in getattr(settings, "movie_languages", []) or []]
    tv_languages = [lang.lower()
                    for lang in getattr(settings, "tv_languages", []) or []]
    anime_languages = [lang.lower()
                       for lang in getattr(settings, "anime_languages", []) or []]
    if movie_languages or tv_languages or anime_languages:
        def language_ok(item: MediaItem) -> bool:
            if item.anime:
                wanted = anime_languages
            elif item.media_type == MOVIE:
                wanted = movie_languages
            else:
                wanted = tv_languages
            return not wanted or item.language is None \
                or item.language.lower() in wanted

        before = len(items)
        items = [i for i in items if language_ok(i)]
        if before != len(items):
            log.info("Original-language filters (movies: %s; tv: %s; anime: %s): "
                     "%d of %d candidates kept",
                     ", ".join(movie_languages) or "any",
                     ", ".join(tv_languages) or "any",
                     ", ".join(anime_languages) or "any",
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
              "skipped": 0, "would_add": 0}
    added_titles: list[str] = []
    error: str | None = None

    state = State(config.state_file, config.retry_not_found_days)
    clients: dict[str, Radarr | Sonarr] = {}
    if config.radarr_enabled:
        clients[MOVIE] = Radarr(config)
    if config.sonarr_enabled:
        clients[TV] = Sonarr(config)
    if not clients:
        error = ("Neither Radarr nor Sonarr is configured - add a connection "
                 "in the web interface")
        log.error("%s", error)

    # Connect to each *arr and load its library once, up front. A client that
    # can't be reached or whose library won't load is taken out of service for
    # this run and its items are deferred to the next run - rather than being
    # retried once per candidate. Without this a single stalled Radarr/Sonarr
    # turns one run into a long string of 60-second timeouts.
    deferred: dict[str, str] = {}   # media_type -> reason its items were skipped
    for media_type, client in clients.items():
        try:
            client.check_connection()
            client.load_library()
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
            if state.should_skip(item.key):
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
                status = client.add(item)
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
            state.record(item.key, status, item.title)
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
            "%d failed, %d previously handled%s",
            counts["added"], counts["exists"], counts["not_found"],
            counts["failed"], counts["skipped"],
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
