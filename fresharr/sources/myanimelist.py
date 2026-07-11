"""Discovery source backed by MyAnimeList, via the Jikan API.

Jikan (jikan.moe) is the free, keyless REST API for MyAnimeList data.
Fetches the current season plus the top airing anime, keeps TV series
and movies, and filters by MAL score. English and default (usually
romaji) titles are both carried as lookup candidates.
"""

import logging

import requests

from ..config import Config
from ..models import MOVIE, TV, MediaItem

log = logging.getLogger(__name__)

API_BASE = "https://api.jikan.moe/v4"

ENDPOINTS = [
    "/seasons/now",
    "/top/anime?filter=airing",
]

TYPE_MAP = {"TV": TV, "ONA": TV, "Movie": MOVIE}


class MyAnimeListSource:
    name = "myanimelist"

    def __init__(self, config: Config):
        self.min_score = config.mal_min_score
        self.min_votes = config.mal_min_votes
        self.session = requests.Session()

    def fetch(self) -> list[MediaItem]:
        items: list[MediaItem] = []
        seen_ids: set[int] = set()
        for endpoint in ENDPOINTS:
            try:
                resp = self.session.get(f"{API_BASE}{endpoint}", timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("MyAnimeList (Jikan) %s failed: %s", endpoint, exc)
                continue
            for entry in data.get("data") or []:
                mal_id = entry.get("mal_id")
                if mal_id in seen_ids:
                    continue
                item = self._parse_item(entry)
                if item:
                    if mal_id:
                        seen_ids.add(mal_id)
                    if (not self.min_score
                            or (item.audience_score or 0) >= self.min_score * 10) \
                            and (not self.min_votes
                                 or (item.votes or 0) >= self.min_votes):
                        items.append(item)
        log.info("MyAnimeList: %d anime pass score >= %.1f",
                 len(items), self.min_score)
        return items

    def _parse_item(self, entry: dict) -> MediaItem | None:
        media_type = TYPE_MAP.get(entry.get("type"))
        if not media_type:
            return None
        english = (entry.get("title_english") or "").strip()
        default = (entry.get("title") or "").strip()
        primary = english or default
        if not primary:
            return None
        alts = tuple(t for t in (default,) if t and t != primary)
        year = entry.get("year")
        if not isinstance(year, int):
            year = (((entry.get("aired") or {}).get("prop") or {})
                    .get("from") or {}).get("year")
        score = entry.get("score")  # 0-10
        return MediaItem(
            title=primary,
            media_type=media_type,
            source=self.name,
            year=year if isinstance(year, int) else None,
            audience_score=round(score * 10) if isinstance(score, (int, float)) else None,
            url=entry.get("url"),
            alt_titles=alts,
            anime=True,
            language="ja",
            votes=entry.get("scored_by")
            if isinstance(entry.get("scored_by"), int) else None,
        )
