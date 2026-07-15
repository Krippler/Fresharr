import logging

import requests

from .. import state
from ..config import Config
from ..models import MediaItem
from .base import (
    ArrClient,
    excluded_language,
    is_already_exists_error,
    lookup_terms,
    pick_best,
)

log = logging.getLogger(__name__)


class Radarr(ArrClient):
    app_name = "Radarr"

    def __init__(self, config: Config):
        super().__init__(config.radarr_url, config.radarr_api_key,
                         config.radarr_quality_profile, config.radarr_root_folder,
                         config.radarr_anime_root_folder, config.radarr_tag,
                         config.arr_timeout)
        self.monitored = config.radarr_monitored
        self.search_on_add = config.radarr_search_on_add
        self.minimum_availability = config.radarr_minimum_availability

    def add(self, item: MediaItem, allowed_languages: list[str] = ()) -> str:
        """Add a movie; returns a state status string."""
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
        # A lookup result already in the library carries its (non-zero) library
        # id, so we detect duplicates without fetching the whole library.
        if match.get("id"):
            return state.EXISTS

        excluded = excluded_language(match, allowed_languages)
        if excluded:
            log.info("Radarr: skipping %s - original language %s is not in the "
                     "selected languages", item.describe(), excluded)
            return state.FILTERED

        payload = dict(match)
        payload.update({
            "qualityProfileId": self.resolve_quality_profile_id(),
            "rootFolderPath": self.resolve_root_folder(item.anime),
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
            if is_already_exists_error(exc):  # backstop if the id check missed it
                return state.EXISTS
            raise
        log.info("Radarr: added %s (%s) [tmdb %s]",
                 added.get("title", item.title), added.get("year", item.year),
                 added.get("tmdbId"))
        return state.ADDED
