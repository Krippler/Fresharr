"""Discovery source backed by The Movie Database's official (free) API.

Uses /discover to find recently released, well-rated titles. Unlike the
Rotten Tomatoes source this is a stable, documented API and returns TMDB
IDs, which makes the Radarr/Sonarr matching exact.
"""

import logging
from datetime import date, timedelta

import requests

from ..config import Config
from ..models import MOVIE, TV, MediaItem

log = logging.getLogger(__name__)

API_BASE = "https://api.themoviedb.org/3"
MAX_PAGES = 3


class TmdbSource:
    name = "tmdb"

    def __init__(self, config: Config):
        self.api_key = config.tmdb_api_key
        self.min_rating_movies = config.tmdb_min_rating_movies
        self.min_rating_tv = config.tmdb_min_rating_tv
        self.min_votes = config.tmdb_min_votes
        self.released_within_days = config.tmdb_released_within_days
        self.include_movies = config.tmdb_movies
        self.include_tv = config.tmdb_tv
        self.back_catalog = config.back_catalog
        self.min_year = config.min_year
        self.session = requests.Session()

    def _date_window(self, gte_key: str, lte_key: str) -> dict:
        today = date.today().isoformat()
        if self.back_catalog:
            # Whole range back to the minimum year (or all-time if unset).
            window = {lte_key: today}
            if self.min_year:
                window[gte_key] = f"{self.min_year:04d}-01-01"
            return window
        since = (date.today() - timedelta(days=self.released_within_days)).isoformat()
        return {gte_key: since, lte_key: today}

    def fetch(self) -> list[MediaItem]:
        # In back-catalog mode sort by vote_count so the well-known, acclaimed
        # titles surface first, rather than obscure films with a few high votes.
        sort = "vote_count.desc" if self.back_catalog else "vote_average.desc"
        items: list[MediaItem] = []
        if self.include_movies:
            items.extend(self._discover(
                "movie", MOVIE, self.min_rating_movies, sort,
                self._date_window("primary_release_date.gte", "primary_release_date.lte")))
        if self.include_tv:
            items.extend(self._discover(
                "tv", TV, self.min_rating_tv, sort,
                self._date_window("first_air_date.gte", "first_air_date.lte")))
        log.info("TMDB: %d items (movies >= %.1f, TV >= %.1f, votes >= %d, %s)",
                 len(items), self.min_rating_movies, self.min_rating_tv,
                 self.min_votes, "back catalog" if self.back_catalog
                 else f"released within {self.released_within_days} days")
        return items

    def _discover(self, kind: str, media_type: str, min_rating: float,
                  sort: str, date_params: dict) -> list[MediaItem]:
        collected: list[MediaItem] = []
        for page in range(1, MAX_PAGES + 1):
            params = {
                "api_key": self.api_key,
                "sort_by": sort,
                "vote_average.gte": min_rating,
                "vote_count.gte": self.min_votes,
                "include_adult": "false",
                "page": page,
                **date_params,
            }
            try:
                resp = self.session.get(f"{API_BASE}/discover/{kind}", params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("TMDB discover/%s page %d failed: %s", kind, page, exc)
                break
            for raw in data.get("results") or []:
                item = self._parse_item(raw, media_type)
                if item:
                    collected.append(item)
            if page >= (data.get("total_pages") or 1):
                break
        return collected

    def _parse_item(self, raw: dict, media_type: str) -> MediaItem | None:
        title = (raw.get("title") or raw.get("name") or "").strip()
        tmdb_id = raw.get("id")
        if not title or not tmdb_id:
            return None
        release = raw.get("release_date") or raw.get("first_air_date") or ""
        year = int(release[:4]) if len(release) >= 4 and release[:4].isdigit() else None
        rating = raw.get("vote_average")
        return MediaItem(
            title=title,
            media_type=media_type,
            source=self.name,
            year=year,
            audience_score=round(rating * 10) if isinstance(rating, (int, float)) else None,
            tmdb_id=int(tmdb_id),
            url=f"https://www.themoviedb.org/{'movie' if media_type == MOVIE else 'tv'}/{tmdb_id}",
            language=raw.get("original_language") or None,
            votes=raw.get("vote_count")
            if isinstance(raw.get("vote_count"), int) else None,
        )
