import logging

import requests

from .. import state
from ..config import Config
from ..models import MediaItem
from ..util import normalize_title
from .base import ArrClient, is_already_exists_error, lookup_terms, pick_best

log = logging.getLogger(__name__)


class Radarr(ArrClient):
    app_name = "Radarr"

    def __init__(self, config: Config):
        super().__init__(config.radarr_url, config.radarr_api_key,
                         config.radarr_quality_profile, config.radarr_root_folder,
                         config.radarr_tag, config.arr_timeout)
        self.monitored = config.radarr_monitored
        self.search_on_add = config.radarr_search_on_add
        self.minimum_availability = config.radarr_minimum_availability
        self._tmdb_ids: set[int] | None = None
        self._title_years: set[tuple[str, int | None]] | None = None

    def load_library(self) -> None:
        movies = self._get("movie")
        self._tmdb_ids = {m["tmdbId"] for m in movies if m.get("tmdbId")}
        self._title_years = {
            (normalize_title(m.get("title", "")), m.get("year")) for m in movies
        }
        log.info("Radarr library: %d movies", len(movies))

    def _in_library(self, item: MediaItem, tmdb_id: int | None) -> bool:
        if self._tmdb_ids is None:
            self.load_library()
        if tmdb_id and tmdb_id in self._tmdb_ids:
            return True
        return (normalize_title(item.title), item.year) in self._title_years

    def add(self, item: MediaItem) -> str:
        """Add a movie; returns a state status string."""
        if self._in_library(item, item.tmdb_id):
            return state.EXISTS

        match = None
        for term in lookup_terms(item):
            candidates = self._get("movie/lookup", term=term)
            match = pick_best(candidates, item.title, item.year, item.tmdb_id,
                              item.alt_titles)
            if match:
                break
        if not match:
            log.info("Radarr: no confident match for %s", item.describe())
            return state.NOT_FOUND
        if self._in_library(item, match.get("tmdbId")):
            return state.EXISTS

        payload = dict(match)
        payload.update({
            "qualityProfileId": self.resolve_quality_profile_id(),
            "rootFolderPath": self.resolve_root_folder(),
            "monitored": self.monitored,
            "minimumAvailability": self.minimum_availability,
            "addOptions": {"searchForMovie": self.search_on_add},
        })
        tag_ids = self.resolve_tag_ids()
        if tag_ids:
            payload["tags"] = tag_ids
        try:
            added = self._post("movie", payload)
        except requests.HTTPError as exc:
            if is_already_exists_error(exc):
                return state.EXISTS
            raise
        self._tmdb_ids.add(match.get("tmdbId") or 0)
        self._title_years.add((normalize_title(match.get("title", "")), match.get("year")))
        log.info("Radarr: added %s (%s) [tmdb %s]",
                 added.get("title", item.title), added.get("year", item.year),
                 added.get("tmdbId"))
        return state.ADDED
