"""Discovery source backed by Rotten Tomatoes' browse pages.

Rotten Tomatoes has no official API. The browse pages at
https://www.rottentomatoes.com/browse/<list> are fed by an internal JSON
endpoint under /napi/browse/<list>, which is what this source calls. The
list path accepts the same filter segments the website uses, e.g.:

    movies_in_theaters/critics:certified_fresh
    movies_at_home/critics:certified_fresh~audience:upright
    tv_series_browse/critics:fresh

Because this is an unofficial endpoint, the payload shape can change
without notice; parsing is intentionally defensive and a schema change
degrades to a logged warning rather than a crash.
"""

import logging
import re

import requests

from ..config import Config
from ..models import MOVIE, TV, MediaItem

log = logging.getLogger(__name__)

BROWSE_API = "https://www.rottentomatoes.com/napi/browse/{path}"

# A browser-like UA is required; the default python-requests UA is blocked.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


class RottenTomatoesSource:
    name = "rottentomatoes"

    def __init__(self, config: Config):
        self.movie_lists = config.rt_movie_lists
        self.tv_lists = config.rt_tv_lists
        self.min_critics = config.rt_min_critics_score
        self.min_audience = config.rt_min_audience_score
        self.max_pages = max(1, config.rt_max_pages)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": "https://www.rottentomatoes.com/browse/movies_in_theaters/",
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
        collected: list[MediaItem] = []
        after = ""
        url = BROWSE_API.format(path=list_path.strip("/"))
        for page in range(self.max_pages):
            params = {"after": after} if after else {}
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("Rotten Tomatoes list %r page %d failed: %s",
                            list_path, page + 1, exc)
                break

            grid = data.get("grid") or {}
            raw_items = grid.get("list") or []
            if not raw_items:
                log.warning(
                    "Rotten Tomatoes list %r returned no items on page %d - "
                    "the list path may be wrong or the endpoint may have changed",
                    list_path, page + 1,
                )
                break
            for raw in raw_items:
                item = self._parse_item(raw, media_type)
                if item:
                    collected.append(item)

            page_info = data.get("pageInfo") or {}
            after = page_info.get("endCursor") or ""
            if not page_info.get("hasNextPage") or not after:
                break
        log.debug("Rotten Tomatoes list %r: %d items", list_path, len(collected))
        return collected

    def _parse_item(self, raw: dict, media_type: str) -> MediaItem | None:
        title = (raw.get("title") or "").strip()
        if not title:
            return None
        media_url = raw.get("mediaUrl") or ""
        return MediaItem(
            title=title,
            media_type=media_type,
            source=self.name,
            year=_extract_year(raw),
            critics_score=_score(raw.get("criticsScore")),
            audience_score=_score(raw.get("audienceScore")),
            url=f"https://www.rottentomatoes.com{media_url}" if media_url else None,
        )

    def _passes_scores(self, item: MediaItem) -> bool:
        if self.min_critics and (item.critics_score or 0) < self.min_critics:
            return False
        if self.min_audience and (item.audience_score or 0) < self.min_audience:
            return False
        return True


def _score(raw) -> int | None:
    """Scores appear as {'score': '93', ...} but have also been plain values."""
    if isinstance(raw, dict):
        raw = raw.get("score")
    if raw in (None, ""):
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _extract_year(raw: dict) -> int | None:
    for field in ("releaseDateText", "publicReleaseDate", "premiereDate"):
        value = raw.get(field)
        if isinstance(value, str):
            match = _YEAR_RE.search(value)
            if match:
                return int(match.group(0))
    return None
