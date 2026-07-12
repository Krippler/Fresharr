"""Registry of discovery sources.

Each source is described by a SourceDef so the web UI can list every
site, show whether it's ready to use, and let the user enable or
disable it individually. Adding a new site means writing a source class
with a fetch() -> list[MediaItem] method and registering it here.
"""

import logging
from dataclasses import dataclass
from typing import Callable

from ..config import Config

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceDef:
    name: str
    label: str
    description: str
    category: str  # UI grouping, e.g. "Movies & TV" or "Anime"
    default_enabled: bool
    requires: str  # env var(s) that must be set, "" if none
    factory: Callable
    detail: Callable[[Config], str]  # short summary of active thresholds

    def is_configured(self, config: Config) -> bool:
        return all(getattr(config, attr) for attr in self._required_attrs())

    def _required_attrs(self) -> list[str]:
        return [part.strip().lower() for part in self.requires.split(",") if part.strip()]


def _rt_factory(config):
    from .rottentomatoes import RottenTomatoesSource
    return RottenTomatoesSource(config)

def _tmdb_factory(config):
    from .tmdb import TmdbSource
    return TmdbSource(config)

def _trakt_factory(config):
    from .trakt import TraktSource
    return TraktSource(config)

def _metacritic_factory(config):
    from .metacritic import MetacriticSource
    return MetacriticSource(config)

def _letterboxd_factory(config):
    from .letterboxd import LetterboxdSource
    return LetterboxdSource(config)

def _anilist_factory(config):
    from .anilist import AniListSource
    return AniListSource(config)

def _mal_factory(config):
    from .myanimelist import MyAnimeListSource
    return MyAnimeListSource(config)


MOVIES_TV = "Movies & TV"
ANIME = "Anime"

SOURCE_DEFS: list[SourceDef] = [
    SourceDef(
        name="rottentomatoes",
        label="Rotten Tomatoes",
        description="Browse lists (Certified Fresh in theaters / at home, Fresh TV) "
                    "filtered by Tomatometer and audience score.",
        category=MOVIES_TV,
        default_enabled=True,
        requires="",
        factory=_rt_factory,
        detail=lambda c: f"critics ≥ {c.rt_min_critics_score}%"
                         + (f", audience ≥ {c.rt_min_audience_score}%"
                            if c.rt_min_audience_score else ""),
    ),
    SourceDef(
        name="metacritic",
        label="Metacritic",
        description="Recent movies and TV from the browse charts, filtered by "
                    "Metascore. No API key needed.",
        category=MOVIES_TV,
        default_enabled=False,
        requires="",
        factory=_metacritic_factory,
        detail=lambda c: f"metascore ≥ {c.metacritic_min_score}",
    ),
    SourceDef(
        name="letterboxd",
        label="Letterboxd",
        description="Films popular this week, filtered by Letterboxd star rating. "
                    "Movies only; no API key needed.",
        category=MOVIES_TV,
        default_enabled=False,
        requires="",
        factory=_letterboxd_factory,
        detail=lambda c: f"rating ≥ {c.letterboxd_min_rating:.1f}/5, "
                         f"top {c.letterboxd_max_films} films",
    ),
    SourceDef(
        name="tmdb",
        label="TMDB",
        description="The Movie Database's official API: recently released, highly "
                    "rated titles. Free API key required (themoviedb.org).",
        category=MOVIES_TV,
        default_enabled=False,
        requires="TMDB_API_KEY",
        factory=_tmdb_factory,
        detail=lambda c: f"rating ≥ {c.tmdb_min_rating:.1f}/10, "
                         f"released within {c.tmdb_released_within_days} days",
    ),
    SourceDef(
        name="trakt",
        label="Trakt",
        description="Trending movies and shows on trakt.tv, filtered by Trakt "
                    "rating. Free API app client ID required (trakt.tv/oauth/applications).",
        category=MOVIES_TV,
        default_enabled=False,
        requires="TRAKT_CLIENT_ID",
        factory=_trakt_factory,
        detail=lambda c: f"rating ≥ {c.trakt_min_rating:.1f}/10",
    ),
    SourceDef(
        name="anilist",
        label="AniList",
        description="Trending anime (series to Sonarr, films to Radarr), filtered "
                    "by AniList score. No API key needed.",
        category=ANIME,
        default_enabled=False,
        requires="",
        factory=_anilist_factory,
        detail=lambda c: f"score ≥ {c.anilist_min_score}/100",
    ),
    SourceDef(
        name="myanimelist",
        label="MyAnimeList",
        description="Current season and top airing anime via the Jikan API, "
                    "filtered by MAL score. No API key needed.",
        category=ANIME,
        default_enabled=False,
        requires="",
        factory=_mal_factory,
        detail=lambda c: f"score ≥ {c.mal_min_score:.1f}/10",
    ),
]

SOURCE_DEFAULTS = {sdef.name: sdef.default_enabled for sdef in SOURCE_DEFS}


def build_sources(config: Config, settings) -> list:
    """Instantiate every source that is enabled in the web UI and has its
    required configuration present."""
    sources = []
    for sdef in SOURCE_DEFS:
        if not settings.is_enabled(sdef.name):
            continue
        if not sdef.is_configured(config):
            log.warning("Source %r is enabled but %s is not set; skipping",
                        sdef.name, sdef.requires)
            continue
        sources.append(sdef.factory(config))
    return sources


def describe_sources(config: Config, settings) -> list[dict]:
    """Source list for the web UI."""
    return [
        {
            "name": sdef.name,
            "label": sdef.label,
            "description": sdef.description,
            "category": sdef.category,
            "detail": sdef.detail(config),
            "enabled": settings.is_enabled(sdef.name),
            "configured": sdef.is_configured(config),
            "requires": sdef.requires,
        }
        for sdef in SOURCE_DEFS
    ]
