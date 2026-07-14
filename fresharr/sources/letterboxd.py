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

HOME_URL = "https://letterboxd.com/"
LIST_URL = "https://letterboxd.com/films/{list_path}/"
FILM_URL = "https://letterboxd.com/film/{slug}/"

# Letterboxd sits behind Cloudflare, which 403s requests that don't look
# like a real browser navigation. A full, self-consistent header set (UA
# matched to the Sec-CH-UA platform) plus priming the session with the
# homepage first (to pick up cookies) gets past the header/reputation
# checks most of the time; a hard JS challenge still can't be solved
# without a browser, so this degrades to a logged warning.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,image/apng,*/*;q=0.8,"
              "application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# Poster slugs appear under different attributes across Letterboxd
# redesigns; each is tried in order.
_SLUG_RES = [
    re.compile(r'data-film-slug="([^"/]+)"'),
    re.compile(r'data-item-slug="([^"/]+)"'),
    re.compile(r'data-target-link="/film/([^"/]+)/"'),
    re.compile(r'href="/film/([^"/]+)/"'),
]
_LD_JSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


class LetterboxdSource:
    name = "letterboxd"

    def __init__(self, config: Config):
        self.min_rating = config.letterboxd_min_rating  # 0-5 stars
        self.min_reviews = config.letterboxd_min_reviews
        self.max_films = config.letterboxd_max_films
        self.list_path = config.letterboxd_list.strip("/")
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        self._primed = False

    def _prime(self) -> None:
        """Warm the session with the homepage so Cloudflare cookies are set
        before the first real request (a browser always has these)."""
        if self._primed:
            return
        self._primed = True
        try:
            self.session.get(HOME_URL, timeout=20)
        except requests.RequestException as exc:
            log.debug("Letterboxd homepage priming failed: %s", exc)

    def fetch(self) -> list[MediaItem]:
        slugs = self._fetch_slugs()
        items = []
        for slug in slugs[: self.max_films]:
            item = self._fetch_film(slug)
            if item and (not self.min_rating
                         or (item.audience_score or 0) >= self.min_rating * 20) \
                    and (not self.min_reviews
                         or (item.votes or 0) >= self.min_reviews):
                items.append(item)
        log.info("Letterboxd: examined %d popular films, %d pass rating >= %.1f/5",
                 min(len(slugs), self.max_films), len(items), self.min_rating)
        return items

    def _get(self, url: str, *, referer: str | None = None):
        headers = {"Sec-Fetch-Site": "same-origin"} if referer else {}
        if referer:
            headers["Referer"] = referer
        return self.session.get(url, headers=headers, timeout=30)

    def _fetch_slugs(self) -> list[str]:
        url = LIST_URL.format(list_path=self.list_path)
        self._prime()
        try:
            resp = self._get(url, referer=HOME_URL)
            # A Cloudflare block is header-driven; re-priming and one retry
            # after a short pause often clears an intermittent 403.
            if resp.status_code == 403:
                import time
                time.sleep(2)
                self._primed = False
                self._prime()
                resp = self._get(url, referer=HOME_URL)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Letterboxd list %r failed: %s (Cloudflare blocks "
                        "server requests; TMDB is the reliable movie source)",
                        self.list_path, exc)
            return []
        slugs: list[str] = []
        for pattern in _SLUG_RES:
            slugs = list(dict.fromkeys(pattern.findall(resp.text)))  # ordered dedupe
            if slugs:
                break
        if not slugs:
            log.warning("Letterboxd list %r: no films parsed - the page layout "
                        "may have changed. %s", self.list_path,
                        _fingerprint(resp.text))
        return slugs

    def _fetch_film(self, slug: str) -> MediaItem | None:
        list_url = LIST_URL.format(list_path=self.list_path)
        try:
            resp = self._get(FILM_URL.format(slug=slug), referer=list_url)
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
        aggregate = data.get("aggregateRating") or {}
        rating = aggregate.get("ratingValue")
        rating_count = aggregate.get("ratingCount")
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
            votes=rating_count if isinstance(rating_count, int) else None,
        )


def _fingerprint(html: str) -> str:
    """Structural summary for log-based diagnosis: which slug markers and
    poster containers are present, plus a sample of any /film/ link."""
    markers = {
        "data-film-slug": html.count("data-film-slug"),
        "data-item-slug": html.count("data-item-slug"),
        "data-target-link": html.count("data-target-link"),
        "/film/ hrefs": html.count('href="/film/'),
        "react-component": html.count("react-component"),
        "poster-container": html.count("poster-container"),
    }
    sample = ""
    idx = html.find("/film/")
    if idx != -1:
        sample = "; sample: " + repr(html[max(0, idx - 60):idx + 40])
    present = ", ".join(f"{k}={v}" for k, v in markers.items())
    return f"{len(html)} bytes; {present}{sample}"


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
