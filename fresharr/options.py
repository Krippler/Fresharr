"""Registry of options that are editable in the web interface.

Each OptionDef maps a web-UI field onto a Config attribute. Values set in
the UI are stored in settings.json and override the environment-variable
defaults at run time (see SettingsStore.apply_to); clearing a field in
the UI falls back to the environment/default value.
"""

from dataclasses import dataclass

# Groups that render as their own cards in the UI (sources render their
# options inline on their own rows).
RADARR = "radarr"
SONARR = "sonarr"
GENERAL = "general"


@dataclass(frozen=True)
class OptionDef:
    key: str      # Config attribute name
    label: str
    group: str    # RADARR / SONARR / GENERAL or a source name
    type: str     # "str" | "secret" | "int" | "float"
    description: str = ""
    min: float | None = None
    max: float | None = None
    is_list: bool = False  # comma-separated string <-> list[str] on Config
    # Populated from the connected app's API and rendered as a dropdown:
    # "profiles" or "root_folders" (see /api/arr/<app>/choices).
    select: str = ""


OPTION_DEFS: list[OptionDef] = [
    # Connections
    OptionDef("radarr_url", "URL", RADARR, "str",
              "e.g. http://host:7878 · empty disables movies"),
    OptionDef("radarr_api_key", "API key", RADARR, "secret",
              "Radarr → Settings → General"),
    OptionDef("radarr_quality_profile", "Quality profile", RADARR, "str",
              "", select="profiles"),
    OptionDef("radarr_root_folder", "Root folder", RADARR, "str",
              "", select="root_folders"),
    OptionDef("sonarr_url", "URL", SONARR, "str",
              "e.g. http://host:8989 · empty disables TV"),
    OptionDef("sonarr_api_key", "API key", SONARR, "secret",
              "Sonarr → Settings → General"),
    OptionDef("sonarr_quality_profile", "Quality profile", SONARR, "str",
              "", select="profiles"),
    OptionDef("sonarr_root_folder", "Root folder", SONARR, "str",
              "", select="root_folders"),
    # General limits
    OptionDef("max_items_per_run", "Max additions per run", GENERAL, "int",
              "Cap per run", min=1, max=500),
    OptionDef("min_year", "Minimum release year", GENERAL, "int",
              "0 = no limit", min=0, max=2100),
    # Per-site thresholds and keys
    OptionDef("rt_min_critics_score", "Min critics score", "rottentomatoes", "int",
              "0-100", min=0, max=100),
    OptionDef("rt_min_audience_score", "Min audience score", "rottentomatoes", "int",
              "0-100 · 0 = off", min=0, max=100),
    OptionDef("rt_movie_lists", "Movie lists", "rottentomatoes", "str",
              "Browse paths after /browse/ (comma-separated)", is_list=True),
    OptionDef("metacritic_min_score", "Min Metascore", "metacritic", "int",
              "0-100", min=0, max=100),
    OptionDef("letterboxd_min_rating", "Min star rating", "letterboxd", "float",
              "0-5", min=0, max=5),
    OptionDef("letterboxd_min_reviews", "Min ratings", "letterboxd", "int",
              "0 = off", min=0),
    OptionDef("tmdb_api_key", "API key", "tmdb", "secret",
              "Free from themoviedb.org"),
    OptionDef("tmdb_min_rating", "Min rating", "tmdb", "float",
              "0-10", min=0, max=10),
    OptionDef("tmdb_min_votes", "Min votes", "tmdb", "int",
              "0 = off", min=0),
    OptionDef("trakt_client_id", "Client ID", "trakt", "secret",
              "Free from trakt.tv/oauth/applications"),
    OptionDef("trakt_min_rating", "Min rating", "trakt", "float",
              "0-10", min=0, max=10),
    OptionDef("trakt_min_votes", "Min votes", "trakt", "int",
              "0 = off", min=0),
    OptionDef("anilist_min_score", "Min score", "anilist", "int",
              "0-100", min=0, max=100),
    OptionDef("mal_min_score", "Min score", "myanimelist", "float",
              "0-10", min=0, max=10),
    OptionDef("mal_min_votes", "Min votes", "myanimelist", "int",
              "0 = off", min=0),
]

OPTIONS_BY_KEY = {defn.key: defn for defn in OPTION_DEFS}


def validate_option(defn: OptionDef, value):
    """Normalize a UI-submitted value; None result means 'clear the
    override and fall back to the environment/default'."""
    from .settings import SettingsError  # avoid import cycle at module load

    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if defn.type in ("str", "secret"):
        return str(value).strip()
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{defn.key} must be a number")
    if defn.min is not None and number < defn.min:
        raise SettingsError(f"{defn.key} must be at least {defn.min:g}")
    if defn.max is not None and number > defn.max:
        raise SettingsError(f"{defn.key} must be at most {defn.max:g}")
    return int(number) if defn.type == "int" else number
