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
        self.min_rating = config.tmdb_min_rating
        self.min_votes = config.tmdb_min_votes
        self.released_within_days = config.tmdb_released_within_days
        self.include_movies = config.tmdb_movies
        self.include_tv = config.tmdb_tv
        self.session = requests.Session()

    def fetch(self) -> list[MediaItem]:
        since = (date.today() - timedelta(days=self.released_within_days)).isoformat()
        items: list[MediaItem] = []
        if self.include_movies:
            items.extend(self._discover(
                "movie", MOVIE,
                {"primary_release_date.gte": since,
                 "primary_release_date.lte": date.today().isoformat()},
            ))
        if self.include_tv:
            items.extend(self._discover(
                "tv", TV,
                {"first_air_date.gte": since,
                 "first_air_date.lte": date.today().isoformat()},
            ))
        log.info("TMDB: %d items (rating >= %.1f, votes >= %d, released since %s)",
                 len(items), self.min_rating, self.min_votes, since)
        return items

    def _discover(self, kind: str, media_type: str, date_params: dict) -> list[MediaItem]:
        collected: list[MediaItem] = []
        for page in range(1, MAX_PAGES + 1):
            params = {
                "api_key": self.api_key,
                "sort_by": "vote_average.desc",
                "vote_average.gte": self.min_rating,
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
        )
