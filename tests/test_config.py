import pytest

from fresharr.config import Config


def _clear_env(monkeypatch):
    import os
    for key in list(os.environ):
        if key.split("_")[0] in ("RT", "TMDB", "TRAKT", "RADARR", "SONARR") \
                or key in ("DRY_RUN", "RUN_ONCE", "MIN_YEAR", "MAX_ITEMS_PER_RUN",
                           "STATE_FILE", "SETTINGS_FILE", "STATUS_FILE", "CONFIG_DIR",
                           "LOG_LEVEL", "RETRY_NOT_FOUND_DAYS", "WEB_PORT"):
            monkeypatch.delenv(key, raising=False)


def test_no_arr_config_is_not_fatal(monkeypatch):
    # Connections can be entered later in the web UI, so startup must not
    # exit when the environment carries no Radarr/Sonarr settings.
    _clear_env(monkeypatch)
    cfg = Config.from_env()
    assert not cfg.radarr_enabled and not cfg.sonarr_enabled


def test_minimal_radarr_config(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "secret")
    cfg = Config.from_env()
    assert cfg.radarr_enabled
    assert not cfg.sonarr_enabled
    assert cfg.rt_min_critics_score == 80
    assert cfg.web_port == 8383
    assert cfg.state_file == "/config/state.json"
    assert cfg.settings_file == "/config/settings.json"


def test_bool_and_list_parsing(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "secret")
    monkeypatch.setenv("DRY_RUN", "TRUE")
    monkeypatch.setenv("RADARR_SEARCH_ON_ADD", "no")
    monkeypatch.setenv("RT_MOVIE_LISTS", " a , b ,, c ")
    cfg = Config.from_env()
    assert cfg.dry_run is True
    assert cfg.radarr_search_on_add is False
    assert cfg.rt_movie_lists == ["a", "b", "c"]
