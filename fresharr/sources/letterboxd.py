"""Discovery source backed by Letterboxd's popular-films pages.

Letterboxd's API is invite-only, so this parses the site itself: the
popular list gives film slugs, and each film page embeds schema.org
JSON-LD with the community rating (0-5 stars). Ratings require one
request per film, so the number of films examined per run is capped.
Parsing is defensive; a redesign degrades to a logged warning.
"""

import json
import logging
import re

import requests

from ..config import Config
from ..models import MOVIE, MediaItem

log = logging.getLogger(__name__)

LIST_URL = "https://letterboxd.com/films/ajax/{list_path}/"
FILM_URL = "https://letterboxd.com/film/{slug}/"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_SLUG_RE = re.compile(r'data-film-slug="([^"/]+)"')
_LD_JSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


class LetterboxdSource:
    name = "letterboxd"

    def __init__(self, config: Config):
        self.min_rating = config.letterboxd_min_rating  # 0-5 stars
        self.max_films = config.letterboxd_max_films
        self.list_path = config.letterboxd_list.strip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch(self) -> list[MediaItem]:
        slugs = self._fetch_slugs()
        items = []
        for slug in slugs[: self.max_films]:
            item = self._fetch_film(slug)
            if item and (not self.min_rating
                         or (item.audience_score or 0) >= self.min_rating * 20):
                items.append(item)
        log.info("Letterboxd: examined %d popular films, %d pass rating >= %.1f/5",
                 min(len(slugs), self.max_films), len(items), self.min_rating)
        return items

    def _fetch_slugs(self) -> list[str]:
        url = LIST_URL.format(list_path=self.list_path)
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Letterboxd list %r failed: %s", self.list_path, exc)
            return []
        slugs = list(dict.fromkeys(_SLUG_RE.findall(resp.text)))  # ordered dedupe
        if not slugs:
            log.warning("Letterboxd list %r: no films parsed - the page layout "
                        "may have changed", self.list_path)
        return slugs

    def _fetch_film(self, slug: str) -> MediaItem | None:
        try:
            resp = self.session.get(FILM_URL.format(slug=slug), timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.debug("Letterboxd film %r failed: %s", slug, exc)
            return None
        data = _extract_ld_json(resp.text)
        if not data:
            return None
        title = (data.get("name") or "").strip()
        if not title:
            return None
        rating = (data.get("aggregateRating") or {}).get("ratingValue")
        year = None
        for event in data.get("releasedEvent") or []:
            match = _YEAR_RE.search(str((event or {}).get("startDate", "")))
            if match:
                year = int(match.group(0))
                break
        return MediaItem(
            title=title,
            media_type=MOVIE,
            source=self.name,
            year=year,
            audience_score=round(float(rating) * 20)
            if isinstance(rating, (int, float)) else None,
            url=FILM_URL.format(slug=slug),
        )


def _extract_ld_json(html: str) -> dict | None:
    for block in _LD_JSON_RE.findall(html):
        text = block.strip()
        # Letterboxd wraps its JSON-LD in CDATA comments
        if text.startswith("/*"):
            end = text.find("*/")
            if end != -1:
                text = text[end + 2:]
        if text.rstrip().endswith("*/"):
            start = text.rfind("/*")
            if start != -1:
                text = text[:start]
        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") in ("Movie", "CreativeWork"):
            return data
    return None
