"""Discovery source backed by Rotten Tomatoes' browse pages.

Rotten Tomatoes has no official API. It previously exposed an internal
JSON endpoint under /napi/browse/<list>, but that was removed (it now
404s), so this source scrapes the rendered browse page HTML instead:

    https://www.rottentomatoes.com/browse/<list>

The list path accepts the same filter segments the website uses, e.g.:

    movies_in_theaters/critics:certified_fresh
    movies_at_home/critics:certified_fresh~audience:upright
    tv_series_browse/critics:fresh

Each result tile is an <a href="/m/..."> (or /tv/...) carrying the
Tomatometer and audience scores as attributes and the title in a
data-qa span. The markup is unofficial and can change without notice;
parsing is defensive and, when a page yields nothing, logs a structural
fingerprint so a break can be diagnosed from the logs.
"""

import html as html_mod
import logging
import re

import requests

from ..config import Config
from ..models import MOVIE, TV, MediaItem

log = logging.getLogger(__name__)

BROWSE_URL = "https://www.rottentomatoes.com/browse/{path}/"

# A browser-like UA is required; the default python-requests UA is blocked.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Each tile links to a title page; chunk the HTML on these anchors.
_TILE_RE = re.compile(r'<a\b[^>]*\bhref="(/(?:m|tv)/[^"]+)"[^>]*>', re.IGNORECASE)
_CRITICS_RE = re.compile(r'criticsscore="(\d{1,3})"', re.IGNORECASE)
_AUDIENCE_RE = re.compile(r'audiencescore="(\d{1,3})"', re.IGNORECASE)
_TITLE_RE = re.compile(
    r'data-qa="discovery-media-list-item-title"[^>]*>\s*([^<]+?)\s*<', re.IGNORECASE)
_DATE_RE = re.compile(
    r'data-qa="discovery-media-list-item-start-date"[^>]*>\s*([^<]+?)\s*<',
    re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


class RottenTomatoesSource:
    name = "rottentomatoes"

    def __init__(self, config: Config):
        self.movie_lists = config.rt_movie_lists
        self.tv_lists = config.rt_tv_lists
        self.min_critics = config.rt_min_critics_score
        self.min_audience = config.rt_min_audience_score
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch(self) -> list[MediaItem]:
        items: list[MediaItem] = []
        for list_path in self.movie_lists:
            items.extend(self._fetch_list(list_path, MOVIE))
        for list_path in self.tv_lists:
            items.extend(self._fetch_list(list_path, TV))
        kept = [item for item in items if self._passes_scores(item)]
        log.info(
            "Rotten Tomatoes: %d items fetched, %d pass score thresholds "
            "(critics >= %d, audience >= %d)",
            len(items), len(kept), self.min_critics, self.min_audience,
        )
        return kept

    def _fetch_list(self, list_path: str, media_type: str) -> list[MediaItem]:
        url = BROWSE_URL.format(path=list_path.strip("/"))
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as exc:
            log.warning("Rotten Tomatoes list %r failed: %s", list_path, exc)
            return []
        items = parse_browse_html(html, media_type, self.name)
        if not items:
            log.warning(
                "Rotten Tomatoes list %r: no items parsed - the list path may "
                "be wrong or the page layout changed. %s",
                list_path, _fingerprint(html))
        log.debug("Rotten Tomatoes list %r: %d items", list_path, len(items))
        return items

    def _passes_scores(self, item: MediaItem) -> bool:
        if self.min_critics and (item.critics_score or 0) < self.min_critics:
            return False
        if self.min_audience and (item.audience_score or 0) < self.min_audience:
            return False
        return True


def parse_browse_html(html: str, media_type: str, source: str) -> list[MediaItem]:
    tiles = list(_TILE_RE.finditer(html))
    items: list[MediaItem] = []
    seen = set()
    for i, tile in enumerate(tiles):
        href = tile.group(1)
        end = tiles[i + 1].start() if i + 1 < len(tiles) else len(html)
        chunk = html[tile.end():end]
        title_match = _TITLE_RE.search(chunk)
        if not title_match:
            continue
        title = html_mod.unescape(title_match.group(1)).strip()
        if not title or href in seen:
            continue
        seen.add(href)
        date_match = _DATE_RE.search(chunk)
        year = None
        if date_match:
            year_match = _YEAR_RE.search(date_match.group(1))
            if year_match:
                year = int(year_match.group(0))
        items.append(MediaItem(
            title=title,
            media_type=media_type,
            source=source,
            year=year,
            critics_score=_score(_CRITICS_RE.search(chunk)),
            audience_score=_score(_AUDIENCE_RE.search(chunk)),
            url=f"https://www.rottentomatoes.com{href}",
        ))
    return items


def _score(match) -> int | None:
    if not match:
        return None
    try:
        return int(match.group(1))
    except (ValueError, IndexError):
        return None


def _fingerprint(html: str) -> str:
    """Structural summary of an unparseable page for log-based diagnosis."""
    return (f"{len(html)} bytes; tile anchors: {len(_TILE_RE.findall(html))}; "
            f"title spans: {len(_TITLE_RE.findall(html))}; "
            f"criticsscore attrs: {len(_CRITICS_RE.findall(html))}")
