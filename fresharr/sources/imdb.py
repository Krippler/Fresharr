"""Discovery source backed by IMDb's popularity charts.

IMDb has no free public API, so this parses the Most Popular Movies
(/chart/moviemeter) and Most Popular TV (/chart/tvmeter) pages. The
charts embed their full dataset as JSON in a <script id="__NEXT_DATA__">
tag, with a schema.org JSON-LD block as a fallback. Both are parsed
defensively; a page redesign degrades to a logged warning.
"""

import json
import logging
import re

import requests

from ..config import Config
from ..models import MOVIE, TV, MediaItem

log = logging.getLogger(__name__)

CHART_URL = "https://www.imdb.com/chart/{chart}/"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_LD_JSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)


class ImdbSource:
    name = "imdb"

    def __init__(self, config: Config):
        self.min_rating = config.imdb_min_rating
        self.min_votes = config.imdb_min_votes
        self.movie_charts = config.imdb_movie_charts
        self.tv_charts = config.imdb_tv_charts
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch(self) -> list[MediaItem]:
        items: list[MediaItem] = []
        for chart in self.movie_charts:
            items.extend(self._fetch_chart(chart, MOVIE))
        for chart in self.tv_charts:
            items.extend(self._fetch_chart(chart, TV))
        kept = [i for i in items
                if (not self.min_rating
                    or (i.audience_score or 0) >= self.min_rating * 10)
                and (not self.min_votes or (i.votes or 0) >= self.min_votes)]
        log.info("IMDb: %d items fetched, %d pass rating >= %.1f, votes >= %d",
                 len(items), len(kept), self.min_rating, self.min_votes)
        return kept

    def _fetch_chart(self, chart: str, media_type: str) -> list[MediaItem]:
        url = CHART_URL.format(chart=chart.strip("/"))
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as exc:
            log.warning("IMDb chart %r failed: %s", chart, exc)
            return []

        items = parse_next_data(html, media_type, self.name)
        if not items:
            items = parse_ld_json(html, media_type, self.name)
        if not items:
            log.warning("IMDb chart %r: no items parsed - the page layout "
                        "may have changed", chart)
        return items


def parse_next_data(html: str, media_type: str, source: str) -> list[MediaItem]:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    items = []
    seen = set()
    for node in _walk_title_nodes(data):
        title = (node.get("titleText") or {}).get("text", "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        year = (node.get("releaseYear") or {}).get("year")
        summary = node.get("ratingsSummary") or {}
        rating = summary.get("aggregateRating")
        votes = summary.get("voteCount")
        title_id = node.get("id") if isinstance(node.get("id"), str) else None
        items.append(MediaItem(
            title=title,
            media_type=media_type,
            source=source,
            year=year if isinstance(year, int) else None,
            audience_score=round(rating * 10) if isinstance(rating, (int, float)) else None,
            url=f"https://www.imdb.com/title/{title_id}/" if title_id else None,
            votes=votes if isinstance(votes, int) else None,
        ))
    return items


def _walk_title_nodes(obj):
    """Yield every dict in the __NEXT_DATA__ tree that looks like a title
    node, wherever IMDb happens to nest the chart this week."""
    if isinstance(obj, dict):
        if "titleText" in obj and ("ratingsSummary" in obj or "releaseYear" in obj):
            yield obj
        else:
            for value in obj.values():
                yield from _walk_title_nodes(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_title_nodes(value)


def parse_ld_json(html: str, media_type: str, source: str) -> list[MediaItem]:
    items = []
    for block in _LD_JSON_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for element in data.get("itemListElement") or []:
            entry = element.get("item") if isinstance(element, dict) else None
            if not isinstance(entry, dict):
                continue
            title = (entry.get("name") or "").strip()
            if not title:
                continue
            aggregate = entry.get("aggregateRating") or {}
            rating = aggregate.get("ratingValue")
            votes = aggregate.get("ratingCount")
            items.append(MediaItem(
                title=title,
                media_type=media_type,
                source=source,
                audience_score=round(float(rating) * 10)
                if isinstance(rating, (int, float, str)) and str(rating).replace(".", "", 1).isdigit()
                else None,
                url=entry.get("url"),
                votes=votes if isinstance(votes, int) else None,
            ))
    return items
