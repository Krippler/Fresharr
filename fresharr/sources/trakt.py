"""Discovery source backed by the official Trakt API.

Uses the trending endpoints (what people are watching right now),
filtered by Trakt's community rating. Requires a free API app client
ID from https://trakt.tv/oauth/applications (no OAuth flow needed for
these public endpoints). Returns TMDB IDs, so Radarr/Sonarr matching
is exact.
"""

import logging

import requests

from .. import __version__
from ..config import Config
from ..models import MOVIE, TV, MediaItem

log = logging.getLogger(__name__)

API_BASE = "https://api.trakt.tv"

# Trakt's API sits behind Cloudflare, which 403s the default
# "python-requests/x.y" User-Agent even when the API key is valid. A named
# User-Agent (Trakt asks clients to identify themselves anyway) gets past it.
USER_AGENT = f"Fresharr/{__version__} (+https://github.com/krippler/fresharr)"


class TraktSource:
    name = "trakt"

    def __init__(self, config: Config):
        self.min_rating = {MOVIE: config.trakt_min_rating_movies,
                           TV: config.trakt_min_rating_tv}
        self.min_votes = config.trakt_min_votes
        self.limit = config.trakt_limit
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": config.trakt_client_id,
        })

    def fetch(self) -> list[MediaItem]:
        items = (self._trending("movies", "movie", MOVIE)
                 + self._trending("shows", "show", TV))
        log.info("Trakt: %d trending items pass rating (movies >= %.1f, "
                 "TV >= %.1f)", len(items), self.min_rating[MOVIE],
                 self.min_rating[TV])
        return items

    def _trending(self, endpoint: str, key: str, media_type: str) -> list[MediaItem]:
        try:
            resp = self.session.get(
                f"{API_BASE}/{endpoint}/trending",
                params={"extended": "full", "limit": self.limit},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if code == 403:
                log.warning("Trakt %s/trending returned 403 Forbidden - the "
                            "Client ID looks wrong. Paste your app's *Client ID* "
                            "(not the Client Secret) from "
                            "trakt.tv/oauth/applications.", endpoint)
            elif code == 429:
                log.warning("Trakt %s/trending rate-limited (429); it will "
                            "recover on the next run.", endpoint)
            else:
                log.warning("Trakt %s/trending failed: %s", endpoint, exc)
            return []
        except (requests.RequestException, ValueError) as exc:
            log.warning("Trakt %s/trending failed: %s", endpoint, exc)
            return []

        items = []
        for entry in data if isinstance(data, list) else []:
            media = entry.get(key) if isinstance(entry, dict) else None
            if not isinstance(media, dict):
                continue
            item = self._parse_item(media, media_type)
            min_rating = self.min_rating[media_type]
            if item and (not min_rating
                         or (item.audience_score or 0) >= min_rating * 10) \
                    and (not self.min_votes
                         or (item.votes or 0) >= self.min_votes):
                items.append(item)
        return items

    def _parse_item(self, media: dict, media_type: str) -> MediaItem | None:
        title = (media.get("title") or "").strip()
        if not title:
            return None
        rating = media.get("rating")
        ids = media.get("ids") or {}
        slug = ids.get("slug")
        kind = "movies" if media_type == MOVIE else "shows"
        return MediaItem(
            title=title,
            media_type=media_type,
            source=self.name,
            year=media.get("year") if isinstance(media.get("year"), int) else None,
            audience_score=round(rating * 10) if isinstance(rating, (int, float)) else None,
            tmdb_id=ids.get("tmdb") if isinstance(ids.get("tmdb"), int) else None,
            url=f"https://trakt.tv/{kind}/{slug}" if slug else None,
            language=media.get("language") or None,
            votes=media.get("votes") if isinstance(media.get("votes"), int) else None,
        )
