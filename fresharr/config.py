"""Environment-variable configuration, fixed at container start.

Connections, credentials, and filter thresholds live here. Scheduling
(run interval) and which discovery sources are enabled deliberately do
NOT: those are managed at runtime through the web interface and stored
in /config/settings.json (see settings.py).
"""

import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()

def _int(name: str, default: int) -> int:
    raw = _str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid integer for %s=%r, using default %s", name, raw, default)
        return default

def _float(name: str, default: float) -> float:
    raw = _str(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid number for %s=%r, using default %s", name, raw, default)
        return default

def _bool(name: str, default: bool) -> bool:
    raw = _str(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")

def _list(name: str, default: str) -> list[str]:
    raw = _str(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass
class Config:
    # Rotten Tomatoes
    rt_movie_lists: list[str] = field(default_factory=list)
    rt_tv_lists: list[str] = field(default_factory=list)
    rt_min_critics_score: int = 80
    rt_min_audience_score: int = 0
    rt_max_pages: int = 2

    # TMDB (separate rating thresholds for movies and TV)
    tmdb_api_key: str = ""
    tmdb_min_rating_movies: float = 7.5
    tmdb_min_rating_tv: float = 7.5
    tmdb_min_votes: int = 50
    tmdb_released_within_days: int = 90
    tmdb_movies: bool = True
    tmdb_tv: bool = True

    # Trakt (separate rating thresholds for movies and TV)
    trakt_client_id: str = ""
    trakt_min_rating_movies: float = 7.0
    trakt_min_rating_tv: float = 7.0
    trakt_min_votes: int = 0
    trakt_limit: int = 40

    # Metacritic (separate Metascore thresholds for movies and TV)
    metacritic_min_score_movies: int = 75
    metacritic_min_score_tv: int = 75

    # Letterboxd
    letterboxd_min_rating: float = 3.5  # 0-5 stars
    letterboxd_min_reviews: int = 0
    letterboxd_max_films: int = 30
    letterboxd_list: str = "popular/this/week"

    # AniList
    anilist_min_score: int = 75  # 0-100

    # MyAnimeList (via Jikan)
    mal_min_score: float = 7.5  # 0-10
    mal_min_votes: int = 0

    # Global filters / limits
    min_year: int = 0
    max_items_per_run: int = 20
    # Back-catalog mode: sources surface the highest-rated titles back to
    # min_year, instead of only what's new/trending.
    back_catalog: bool = False

    # Radarr
    radarr_url: str = ""
    radarr_api_key: str = ""
    radarr_quality_profile: str = ""
    radarr_root_folder: str = ""
    radarr_monitored: bool = True
    radarr_search_on_add: bool = True
    radarr_minimum_availability: str = "released"
    radarr_tag: str = ""

    # Sonarr
    sonarr_url: str = ""
    sonarr_api_key: str = ""
    sonarr_quality_profile: str = ""
    sonarr_root_folder: str = ""
    sonarr_monitored: bool = True
    # Off by default: series are added but not auto-searched, so Sonarr
    # doesn't kick off downloads for every freshly discovered show.
    sonarr_search_on_add: bool = False
    sonarr_tag: str = ""

    # HTTP timeout (seconds) for Radarr/Sonarr library reads and adds. Large
    # libraries and metadata refreshes can take a while, so this is generous.
    arr_timeout: int = 300

    # Runtime behaviour
    dry_run: bool = False
    run_once: bool = False
    retry_not_found_days: int = 7
    web_port: int = 8383
    state_file: str = ""
    settings_file: str = ""
    status_file: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        config_dir = _str("CONFIG_DIR", "/config")
        # Legacy single-threshold env vars seed both the movie and TV
        # defaults, so existing setups keep working after the split.
        tmdb_rating = _float("TMDB_MIN_RATING", 7.5)
        trakt_rating = _float("TRAKT_MIN_RATING", 7.0)
        metacritic_score = _int("METACRITIC_MIN_SCORE", 75)
        cfg = cls(
            rt_movie_lists=_list(
                # Theatrical certified-fresh only by default: its dates are
                # real release dates. The movies_at_home list is a streaming
                # *catalog* (all-time classics newly on streaming, dated by
                # streaming availability), which floods results with old films
                # mislabelled with the current year - opt in explicitly if
                # wanted.
                "RT_MOVIE_LISTS",
                "movies_in_theaters/critics:certified_fresh",
            ),
            # No TV list by default: RT's "fresh TV" browse is an evergreen
            # catalog (long-running shows, no release year), not a new-shows
            # feed, so it surfaced old series. Opt in with a browse path if
            # wanted; Metacritic covers new TV reliably.
            rt_tv_lists=_list("RT_TV_LISTS", ""),
            rt_min_critics_score=_int("RT_MIN_CRITICS_SCORE", 80),
            rt_min_audience_score=_int("RT_MIN_AUDIENCE_SCORE", 0),
            rt_max_pages=_int("RT_MAX_PAGES", 2),
            tmdb_api_key=_str("TMDB_API_KEY"),
            tmdb_min_rating_movies=_float("TMDB_MIN_RATING_MOVIES", tmdb_rating),
            tmdb_min_rating_tv=_float("TMDB_MIN_RATING_TV", tmdb_rating),
            tmdb_min_votes=_int("TMDB_MIN_VOTES", 50),
            tmdb_released_within_days=_int("TMDB_RELEASED_WITHIN_DAYS", 90),
            tmdb_movies=_bool("TMDB_MOVIES", True),
            tmdb_tv=_bool("TMDB_TV", True),
            trakt_client_id=_str("TRAKT_CLIENT_ID"),
            trakt_min_rating_movies=_float("TRAKT_MIN_RATING_MOVIES", trakt_rating),
            trakt_min_rating_tv=_float("TRAKT_MIN_RATING_TV", trakt_rating),
            trakt_min_votes=_int("TRAKT_MIN_VOTES", 0),
            trakt_limit=_int("TRAKT_LIMIT", 40),
            metacritic_min_score_movies=_int("METACRITIC_MIN_SCORE_MOVIES", metacritic_score),
            metacritic_min_score_tv=_int("METACRITIC_MIN_SCORE_TV", metacritic_score),
            letterboxd_min_rating=_float("LETTERBOXD_MIN_RATING", 3.5),
            letterboxd_min_reviews=_int("LETTERBOXD_MIN_REVIEWS", 0),
            letterboxd_max_films=_int("LETTERBOXD_MAX_FILMS", 30),
            letterboxd_list=_str("LETTERBOXD_LIST", "popular/this/week"),
            anilist_min_score=_int("ANILIST_MIN_SCORE", 75),
            mal_min_score=_float("MAL_MIN_SCORE", 7.5),
            mal_min_votes=_int("MAL_MIN_VOTES", 0),
            min_year=_int("MIN_YEAR", 0),
            max_items_per_run=_int("MAX_ITEMS_PER_RUN", 20),
            back_catalog=_bool("BACK_CATALOG", False),
            radarr_url=_str("RADARR_URL"),
            radarr_api_key=_str("RADARR_API_KEY"),
            radarr_quality_profile=_str("RADARR_QUALITY_PROFILE"),
            radarr_root_folder=_str("RADARR_ROOT_FOLDER"),
            radarr_monitored=_bool("RADARR_MONITORED", True),
            radarr_search_on_add=_bool("RADARR_SEARCH_ON_ADD", True),
            radarr_minimum_availability=_str("RADARR_MINIMUM_AVAILABILITY", "released"),
            radarr_tag=_str("RADARR_TAG"),
            sonarr_url=_str("SONARR_URL"),
            sonarr_api_key=_str("SONARR_API_KEY"),
            sonarr_quality_profile=_str("SONARR_QUALITY_PROFILE"),
            sonarr_root_folder=_str("SONARR_ROOT_FOLDER"),
            sonarr_monitored=_bool("SONARR_MONITORED", True),
            sonarr_search_on_add=_bool("SONARR_SEARCH_ON_ADD", False),
            sonarr_tag=_str("SONARR_TAG"),
            arr_timeout=_int("ARR_TIMEOUT", 300),
            dry_run=_bool("DRY_RUN", False),
            run_once=_bool("RUN_ONCE", False),
            retry_not_found_days=_int("RETRY_NOT_FOUND_DAYS", 7),
            web_port=_int("WEB_PORT", 8383),
            state_file=_str("STATE_FILE", os.path.join(config_dir, "state.json")),
            settings_file=_str("SETTINGS_FILE", os.path.join(config_dir, "settings.json")),
            status_file=_str("STATUS_FILE", os.path.join(config_dir, "status.json")),
            log_level=_str("LOG_LEVEL", "INFO").upper(),
        )
        cfg.validate()
        return cfg

    @property
    def radarr_enabled(self) -> bool:
        return bool(self.radarr_url and self.radarr_api_key)

    @property
    def sonarr_enabled(self) -> bool:
        return bool(self.sonarr_url and self.sonarr_api_key)

    def validate(self) -> None:
        if not self.radarr_enabled and not self.sonarr_enabled:
            # Not fatal: connections can be entered in the web interface.
            log.warning(
                "No Radarr/Sonarr connection configured yet - open the web "
                "interface (port %d) to add one.", self.web_port,
            )
        for legacy in ("SOURCES", "RUN_INTERVAL_DAYS", "RUN_INTERVAL_HOURS"):
            if os.environ.get(legacy):
                log.warning(
                    "%s is no longer read from the environment - the run schedule "
                    "and source selection are managed in the Fresharr web "
                    "interface (port %d)", legacy, self.web_port,
                )
