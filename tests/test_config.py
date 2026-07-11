import pytest

from fresharr.config import Config


def _clear_env(monkeypatch):
    import os
    for key in list(os.environ):
        if key.split("_")[0] in ("RT", "TMDB", "RADARR", "SONARR") or key in (
            "SOURCES", "DRY_RUN", "RUN_ONCE", "RUN_INTERVAL_DAYS", "MIN_YEAR",
            "MAX_ITEMS_PER_RUN", "STATE_FILE", "CONFIG_DIR", "LOG_LEVEL",
            "RETRY_NOT_FOUND_DAYS",
        ):
            monkeypatch.delenv(key, raising=False)


def test_requires_at_least_one_arr(monkeypatch):
    _clear_env(monkeypatch)
    with pytest.raises(SystemExit):
        Config.from_env()


def test_minimal_radarr_config(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "secret")
    cfg = Config.from_env()
    assert cfg.radarr_enabled
    assert not cfg.sonarr_enabled
    assert cfg.sources == ["rottentomatoes"]
    assert cfg.rt_min_critics_score == 80
    assert cfg.state_file == "/config/state.json"


def test_tmdb_source_requires_key(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "secret")
    monkeypatch.setenv("SOURCES", "rottentomatoes,tmdb")
    with pytest.raises(SystemExit):
        Config.from_env()
    monkeypatch.setenv("TMDB_API_KEY", "abc")
    assert Config.from_env().sources == ["rottentomatoes", "tmdb"]


def test_unknown_source_rejected(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "secret")
    monkeypatch.setenv("SOURCES", "imdb")
    with pytest.raises(SystemExit):
        Config.from_env()


def test_run_interval_clamped_to_daily_minimum(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "secret")
    assert Config.from_env().run_interval_days == 1.0  # default is daily

    monkeypatch.setenv("RUN_INTERVAL_DAYS", "0.5")
    assert Config.from_env().run_interval_days == 1.0  # sub-daily clamped up

    monkeypatch.setenv("RUN_INTERVAL_DAYS", "7")
    assert Config.from_env().run_interval_days == 7.0  # longer is fine


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
