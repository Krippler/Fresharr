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
    # Which discovery sources to use
    sources: list[str] = field(default_factory=list)

    # Rotten Tomatoes
    rt_movie_lists: list[str] = field(default_factory=list)
    rt_tv_lists: list[str] = field(default_factory=list)
    rt_min_critics_score: int = 80
    rt_min_audience_score: int = 0
    rt_max_pages: int = 2

    # TMDB
    tmdb_api_key: str = ""
    tmdb_min_rating: float = 7.5
    tmdb_min_votes: int = 50
    tmdb_released_within_days: int = 90
    tmdb_movies: bool = True
    tmdb_tv: bool = True

    # Global filters / limits
    min_year: int = 0
    max_items_per_run: int = 20

    # Radarr
    radarr_url: str = ""
    radarr_api_key: str = ""
    radarr_quality_profile: str = ""
    radarr_root_folder: str = ""
    radarr_monitored: bool = True
    radarr_search_on_add: bool = True
    radarr_minimum_availability: str = "released"

    # Sonarr
    sonarr_url: str = ""
    sonarr_api_key: str = ""
    sonarr_quality_profile: str = ""
    sonarr_root_folder: str = ""
    sonarr_monitored: bool = True
    sonarr_search_on_add: bool = True

    # Runtime behaviour
    dry_run: bool = False
    run_once: bool = False
    run_interval_days: float = 1.0  # never runs more often than daily
    retry_not_found_days: int = 7
    state_file: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        config_dir = _str("CONFIG_DIR", "/config")
        cfg = cls(
            sources=[s.lower() for s in _list("SOURCES", "rottentomatoes")],
            rt_movie_lists=_list(
                "RT_MOVIE_LISTS",
                "movies_in_theaters/critics:certified_fresh,"
                "movies_at_home/critics:certified_fresh",
            ),
            rt_tv_lists=_list("RT_TV_LISTS", "tv_series_browse/critics:fresh"),
            rt_min_critics_score=_int("RT_MIN_CRITICS_SCORE", 80),
            rt_min_audience_score=_int("RT_MIN_AUDIENCE_SCORE", 0),
            rt_max_pages=_int("RT_MAX_PAGES", 2),
            tmdb_api_key=_str("TMDB_API_KEY"),
            tmdb_min_rating=_float("TMDB_MIN_RATING", 7.5),
            tmdb_min_votes=_int("TMDB_MIN_VOTES", 50),
            tmdb_released_within_days=_int("TMDB_RELEASED_WITHIN_DAYS", 90),
            tmdb_movies=_bool("TMDB_MOVIES", True),
            tmdb_tv=_bool("TMDB_TV", True),
            min_year=_int("MIN_YEAR", 0),
            max_items_per_run=_int("MAX_ITEMS_PER_RUN", 20),
            radarr_url=_str("RADARR_URL"),
            radarr_api_key=_str("RADARR_API_KEY"),
            radarr_quality_profile=_str("RADARR_QUALITY_PROFILE"),
            radarr_root_folder=_str("RADARR_ROOT_FOLDER"),
            radarr_monitored=_bool("RADARR_MONITORED", True),
            radarr_search_on_add=_bool("RADARR_SEARCH_ON_ADD", True),
            radarr_minimum_availability=_str("RADARR_MINIMUM_AVAILABILITY", "released"),
            sonarr_url=_str("SONARR_URL"),
            sonarr_api_key=_str("SONARR_API_KEY"),
            sonarr_quality_profile=_str("SONARR_QUALITY_PROFILE"),
            sonarr_root_folder=_str("SONARR_ROOT_FOLDER"),
            sonarr_monitored=_bool("SONARR_MONITORED", True),
            sonarr_search_on_add=_bool("SONARR_SEARCH_ON_ADD", True),
            dry_run=_bool("DRY_RUN", False),
            run_once=_bool("RUN_ONCE", False),
            run_interval_days=_float("RUN_INTERVAL_DAYS", 1.0),
            retry_not_found_days=_int("RETRY_NOT_FOUND_DAYS", 7),
            state_file=_str("STATE_FILE", os.path.join(config_dir, "state.json")),
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
            raise SystemExit(
                "Nothing to do: configure at least one of Radarr "
                "(RADARR_URL + RADARR_API_KEY) or Sonarr (SONARR_URL + SONARR_API_KEY)."
            )
        if "tmdb" in self.sources and not self.tmdb_api_key:
            raise SystemExit("SOURCES includes 'tmdb' but TMDB_API_KEY is not set.")
        unknown = [s for s in self.sources if s not in ("rottentomatoes", "tmdb")]
        if unknown:
            raise SystemExit(f"Unknown SOURCES entries: {', '.join(unknown)} "
                             "(valid: rottentomatoes, tmdb)")
        if not self.sources:
            raise SystemExit("SOURCES is empty; set at least one of: rottentomatoes, tmdb")
        if self.run_interval_days < 1.0:
            log.warning(
                "RUN_INTERVAL_DAYS=%s is below the daily minimum; using 1 day. "
                "Discovery lists change slowly and the sites don't need more traffic.",
                self.run_interval_days,
            )
            self.run_interval_days = 1.0
