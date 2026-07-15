import logging

import requests

from .. import state
from ..config import Config
from ..models import MediaItem
from ..util import normalize_title
from .base import ArrClient, is_already_exists_error, lookup_terms, pick_best

log = logging.getLogger(__name__)


class Sonarr(ArrClient):
    app_name = "Sonarr"

    def __init__(self, config: Config):
        super().__init__(config.sonarr_url, config.sonarr_api_key,
                         config.sonarr_quality_profile, config.sonarr_root_folder,
                         config.sonarr_tag, config.arr_timeout)
        self.monitored = config.sonarr_monitored
        self.search_on_add = config.sonarr_search_on_add
        self._tvdb_ids: set[int] | None = None
        self._title_years: set[tuple[str, int | None]] | None = None
        self._language_profile_id: int | None = None
        self._language_profile_checked = False

    def load_library(self) -> None:
        series = self._get("series")
        self._tvdb_ids = {s["tvdbId"] for s in series if s.get("tvdbId")}
        self._title_years = {
            (normalize_title(s.get("title", "")), s.get("year")) for s in series
        }
        log.info("Sonarr library: %d series", len(series))

    def _in_library(self, item: MediaItem, tvdb_id: int | None) -> bool:
        if self._tvdb_ids is None:
            self.load_library()
        if tvdb_id and tvdb_id in self._tvdb_ids:
            return True
        return (normalize_title(item.title), item.year) in self._title_years

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

    def add(self, item: MediaItem) -> str:
        """Add a series; returns a state status string."""
        if self._in_library(item, None):
            return state.EXISTS

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
        if self._in_library(item, match["tvdbId"]):
            return state.EXISTS

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
            if is_already_exists_error(exc):
                return state.EXISTS
            raise
        self._tvdb_ids.add(match["tvdbId"])
        self._title_years.add((normalize_title(match.get("title", "")), match.get("year")))
        log.info("Sonarr: added %s (%s) [tvdb %s]",
                 added.get("title", item.title), added.get("year", item.year),
                 added.get("tvdbId"))
        return state.ADDED
