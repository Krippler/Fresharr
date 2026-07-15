"""Discovery source backed by Metacritic's browse pages.

Metacritic has no public API, so this parses the server-rendered
browse pages (/browse/movie/, /browse/tv/), which carry each product
card's title in a data-title attribute and its Metascore in an
accessibility title ("Metascore NN out of 100"). Recent releases are
requested via the releaseYearMin query parameter. Parsing is
defensive; a redesign degrades to a logged warning.
"""

import html as html_mod
import logging
import re
from datetime import date

import requests

from ..config import Config
from ..models import MOVIE, TV, MediaItem

log = logging.getLogger(__name__)

BROWSE_URL = "https://www.metacritic.com/browse/{kind}/"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_TITLE_RE = re.compile(r'data-title="([^"]+)"')
_SCORE_RE = re.compile(r"Metascore (\d{1,3}) out of 100")
# "Jan 5, 2026" - the release date shown on each card
_DATE_RE = re.compile(r"[A-Z][a-z]{2,8}\.? \d{1,2}, ((?:19|20)\d{2})")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
# Titles like "Forever (2025)" carry their year as a disambiguator
_TITLE_YEAR_RE = re.compile(r"^(.*\S)\s+\(((?:19|20)\d{2})\)$")
# href/src values can contain numbers that look like years
# (e.g. /movie/2000-meters-to-andriivka/), so they're stripped before
# falling back to a bare year search
_ATTR_RE = re.compile(r'(?:href|src)="[^"]*"')


class MetacriticSource:
    name = "metacritic"

    def __init__(self, config: Config):
        self.min_score = {MOVIE: config.metacritic_min_score_movies,
                          TV: config.metacritic_min_score_tv}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch(self) -> list[MediaItem]:
        items = (self._fetch_browse("movie", MOVIE)
                 + self._fetch_browse("tv", TV))
        kept = [i for i in items
                if not self.min_score[i.media_type]
                or (i.critics_score or 0) >= self.min_score[i.media_type]]
        log.info("Metacritic: %d items fetched, %d pass metascore "
                 "(movies >= %d, TV >= %d)", len(items), len(kept),
                 self.min_score[MOVIE], self.min_score[TV])
        return kept

    def _fetch_browse(self, kind: str, media_type: str) -> list[MediaItem]:
        try:
            resp = self.session.get(
                BROWSE_URL.format(kind=kind),
                params={"releaseYearMin": date.today().year - 1},
                timeout=30,
            )
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as exc:
            log.warning("Metacritic browse/%s failed: %s", kind, exc)
            return []
        items = parse_browse_html(html, media_type, self.name)
        if not items:
            log.warning("Metacritic browse/%s: no items parsed - the page "
                        "layout may have changed", kind)
        return items


def parse_browse_html(html: str, media_type: str, source: str) -> list[MediaItem]:
    # Chunk the page on data-title attributes: everything between one title
    # and the next belongs to that product card (its Metascore, its date).
    title_matches = list(_TITLE_RE.finditer(html))
    items = []
    seen = set()
    for i, title_match in enumerate(title_matches):
        title = html_mod.unescape(title_match.group(1)).strip()
        if not title or title in seen:
            continue
        seen.add(title)
        title_year = None
        title_year_match = _TITLE_YEAR_RE.match(title)
        if title_year_match:
            title = title_year_match.group(1)
            title_year = int(title_year_match.group(2))
        end = title_matches[i + 1].start() if i + 1 < len(title_matches) else len(html)
        chunk = html[title_match.end():end]
        score_match = _SCORE_RE.search(chunk)
        items.append(MediaItem(
            title=title,
            media_type=media_type,
            source=source,
            year=_extract_year(chunk, title_year),
            critics_score=int(score_match.group(1)) if score_match else None,
        ))
    return items


def _extract_year(chunk: str, title_year: int | None) -> int | None:
    date_match = _DATE_RE.search(chunk)
    if date_match:
        return int(date_match.group(1))
    if title_year:
        return title_year
    year_match = _YEAR_RE.search(_ATTR_RE.sub("", chunk))
    return int(year_match.group(0)) if year_match else None
