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


class Sonarr(ArrClient):
    app_name = "Sonarr"

    def __init__(self, config: Config):
        super().__init__(config.sonarr_url, config.sonarr_api_key,
                         config.sonarr_quality_profile, config.sonarr_root_folder,
                         config.sonarr_tag, config.arr_timeout)
        self.monitored = config.sonarr_monitored
        self.search_on_add = config.sonarr_search_on_add
        self._language_profile_id: int | None = None
        self._language_profile_checked = False

    def _language_profile(self) -> int | None:
        """Sonarr v3 requires a languageProfileId; v4 removed the endpoint."""
        if not self._language_profile_checked:
            self._language_profile_checked = True
            try:
                profiles = self._get("languageprofile")
                if profiles:
                    self._language_profile_id = profiles[0]["id"]
            except requests.RequestException:
                self._language_profile_id = None
        return self._language_profile_id

    def add(self, item: MediaItem, allowed_languages: list[str] = ()) -> str:
        """Add a series; returns a state status string."""
        match = None
        for term in lookup_terms(item):
            candidates = self._get("series/lookup", term=term)
            match = pick_best(candidates, item.title, item.year, item.tmdb_id,
                              item.alt_titles)
            if match and match.get("tvdbId"):
                break
            match = None
        if not match:
            log.info("Sonarr: no confident match for %s", item.describe())
            return state.NOT_FOUND
        # A lookup result already in the library carries its (non-zero) library
        # id, so we detect duplicates without fetching the whole library.
        if match.get("id"):
            return state.EXISTS

        excluded = excluded_language(match, allowed_languages)
        if excluded:
            log.info("Sonarr: skipping %s - original language %s is not in the "
                     "selected languages", item.describe(), excluded)
            return state.FILTERED

        payload = dict(match)
        payload.update({
            "qualityProfileId": self.resolve_quality_profile_id(),
            "rootFolderPath": self.resolve_root_folder(),
            "monitored": self.monitored,
            "seasonFolder": True,
            "seriesType": "anime" if item.anime else "standard",
            "addOptions": {"searchForMissingEpisodes": self.search_on_add},
        })
        language_profile_id = self._language_profile()
        if language_profile_id is not None:
            payload["languageProfileId"] = language_profile_id
        tag_ids = self.resolve_tag_ids()
        if tag_ids:
            payload["tags"] = tag_ids
        try:
            added = self._post("series", payload)
        except requests.HTTPError as exc:
            if is_already_exists_error(exc):  # backstop if the id check missed it
                return state.EXISTS
            raise
        log.info("Sonarr: added %s (%s) [tvdb %s]",
                 added.get("title", item.title), added.get("year", item.year),
                 added.get("tvdbId"))
        return state.ADDED
