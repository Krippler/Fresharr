"""Discovery source backed by AniList's official GraphQL API.

Free, no API key required. Fetches currently trending anime and keeps
TV series (for Sonarr, flagged as anime for absolute episode numbering)
and movies (for Radarr), filtered by AniList's community score. Both
the English and romaji titles are carried as lookup candidates since
TVDB/TMDB may index either.
"""

import logging

import requests

from ..config import Config
from ..models import MOVIE, TV, MediaItem

log = logging.getLogger(__name__)

API_URL = "https://graphql.anilist.co"

QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: ANIME, sort: TRENDING_DESC) {
      id
      title { romaji english }
      format
      averageScore
      seasonYear
      startDate { year }
    }
  }
}
"""

# AniList format -> Fresharr media type. OVAs and specials are skipped:
# they rarely map cleanly onto Sonarr series.
FORMAT_MAP = {"TV": TV, "TV_SHORT": TV, "ONA": TV, "MOVIE": MOVIE}


class AniListSource:
    name = "anilist"

    def __init__(self, config: Config):
        self.min_score = config.anilist_min_score
        self.per_page = 50
        self.session = requests.Session()

    def fetch(self) -> list[MediaItem]:
        try:
            resp = self.session.post(
                API_URL,
                json={"query": QUERY,
                      "variables": {"page": 1, "perPage": self.per_page}},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("AniList query failed: %s", exc)
            return []

        media = (((data.get("data") or {}).get("Page") or {}).get("media")) or []
        items = []
        for entry in media:
            item = self._parse_item(entry)
            if item and (not self.min_score
                         or (item.audience_score or 0) >= self.min_score):
                items.append(item)
        log.info("AniList: %d of %d trending anime pass score >= %d",
                 len(items), len(media), self.min_score)
        return items

    def _parse_item(self, entry: dict) -> MediaItem | None:
        media_type = FORMAT_MAP.get(entry.get("format"))
        if not media_type:
            return None
        titles = entry.get("title") or {}
        english = (titles.get("english") or "").strip()
        romaji = (titles.get("romaji") or "").strip()
        primary = english or romaji
        if not primary:
            return None
        alts = tuple(t for t in (romaji,) if t and t != primary)
        year = entry.get("seasonYear") or (entry.get("startDate") or {}).get("year")
        score = entry.get("averageScore")  # already 0-100
        anilist_id = entry.get("id")
        return MediaItem(
            title=primary,
            media_type=media_type,
            source=self.name,
            year=year if isinstance(year, int) else None,
            audience_score=score if isinstance(score, int) else None,
            url=f"https://anilist.co/anime/{anilist_id}" if anilist_id else None,
            alt_titles=alts,
            anime=True,
        )
