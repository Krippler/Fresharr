import json

import pytest

from fresharr.settings import SettingsError, SettingsStore

DEFAULTS = {"rottentomatoes": True, "metacritic": False, "tmdb": False, "trakt": False}


def make_store(tmp_path) -> SettingsStore:
    return SettingsStore(str(tmp_path / "settings.json"), DEFAULTS)


def test_defaults(tmp_path):
    store = make_store(tmp_path)
    assert store.run_interval_days == 1.0
    assert store.is_enabled("rottentomatoes")
    assert not store.is_enabled("metacritic")
    assert not store.is_enabled("nonexistent")


def test_update_persists_across_reload(tmp_path):
    store = make_store(tmp_path)
    store.update({"run_interval_days": 7,
                  "sources": {"metacritic": {"enabled": True},
                              "rottentomatoes": {"enabled": False}}})

    reloaded = make_store(tmp_path)
    assert reloaded.run_interval_days == 7.0
    assert reloaded.is_enabled("metacritic")
    assert not reloaded.is_enabled("rottentomatoes")


def test_interval_clamped_to_daily_minimum(tmp_path):
    store = make_store(tmp_path)
    snapshot = store.update({"run_interval_days": 0.25})
    assert snapshot["run_interval_days"] == 1.0
    # A hand-edited settings file can't bypass the floor either
    (tmp_path / "settings.json").write_text(
        json.dumps({"run_interval_days": 0.01}))
    assert make_store(tmp_path).run_interval_days == 1.0


def test_unknown_source_rejected(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(SettingsError, match="Unknown source"):
        store.update({"sources": {"unknownsrc": {"enabled": True}}})


def test_malformed_payloads_rejected(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(SettingsError):
        store.update({"run_interval_days": "soon"})
    with pytest.raises(SettingsError):
        store.update({"sources": {"metacritic": {"enabled": "yes"}}})
    with pytest.raises(SettingsError):
        store.update(None)


def test_languages_roundtrip_and_defaults(tmp_path):
    store = make_store(tmp_path)
    assert store.movie_languages == []  # empty = all languages
    assert store.tv_languages == []
    assert store.anime_languages == []

    store.update({"movie_languages": ["en", "fr", "en"],
                  "tv_languages": ["ko"],
                  "anime_languages": ["ja"]})
    reloaded = make_store(tmp_path)
    assert reloaded.movie_languages == ["en", "fr"]  # deduped, sorted
    assert reloaded.tv_languages == ["ko"]
    assert reloaded.anime_languages == ["ja"]

    # The lists are independent
    reloaded.update({"movie_languages": []})
    assert reloaded.movie_languages == []
    assert reloaded.tv_languages == ["ko"]
    assert reloaded.anime_languages == ["ja"]


def test_legacy_combined_language_list_still_applies(tmp_path):
    # Settings written before the movie/tv split used a single "languages"
    # key that covered both.
    (tmp_path / "settings.json").write_text(json.dumps({"languages": ["en"]}))
    store = make_store(tmp_path)
    assert store.movie_languages == ["en"]
    assert store.tv_languages == ["en"]
    assert store.anime_languages == []
    # Setting a split list takes precedence over the legacy key
    store.update({"tv_languages": ["ko"]})
    assert store.tv_languages == ["ko"]
    assert store.movie_languages == ["en"]


def test_invalid_language_codes_rejected(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(SettingsError, match="Invalid language code"):
        store.update({"movie_languages": ["english"]})
    with pytest.raises(SettingsError, match="Invalid language code"):
        store.update({"anime_languages": ["<script>"]})
    with pytest.raises(SettingsError):
        store.update({"tv_languages": "en"})


def test_partial_update_leaves_rest_alone(tmp_path):
    store = make_store(tmp_path)
    store.update({"run_interval_days": 3})
    store.update({"sources": {"metacritic": {"enabled": True}}})
    snapshot = store.snapshot()
    assert snapshot["run_interval_days"] == 3.0
    assert snapshot["sources"]["metacritic"]["enabled"]
    assert snapshot["sources"]["rottentomatoes"]["enabled"]  # untouched default


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    (tmp_path / "settings.json").write_text("{oops")
    store = make_store(tmp_path)
    assert store.run_interval_days == 1.0
    assert store.is_enabled("rottentomatoes")


def test_options_override_env_config(tmp_path):
    from fresharr.config import Config
    store = make_store(tmp_path)
    store.update({"options": {
        "radarr_url": "http://radarr:7878/",
        "radarr_api_key": "ui-key",
        "rt_min_critics_score": "90",
        "metacritic_min_score": 88,
        "rt_movie_lists": "movies_in_theaters, movies_at_home",
    }})

    env_config = Config(tmdb_api_key="env-tmdb")
    effective = make_store(tmp_path).apply_to(env_config)
    assert effective.radarr_url == "http://radarr:7878/"
    assert effective.radarr_api_key == "ui-key"
    assert effective.radarr_enabled
    assert effective.rt_min_critics_score == 90       # coerced to int
    assert effective.metacritic_min_score == 88
    assert effective.rt_movie_lists == ["movies_in_theaters", "movies_at_home"]
    assert effective.tmdb_api_key == "env-tmdb"       # env value untouched
    assert env_config.rt_min_critics_score == 80      # original not mutated


def test_option_cleared_falls_back_to_env(tmp_path):
    from fresharr.config import Config
    store = make_store(tmp_path)
    store.update({"options": {"rt_min_critics_score": 90}})
    store.update({"options": {"rt_min_critics_score": ""}})  # cleared in UI
    assert store.apply_to(Config()).rt_min_critics_score == 80
    assert "rt_min_critics_score" not in store.options()


def test_option_validation(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(SettingsError, match="Unknown option"):
        store.update({"options": {"not_an_option": 1}})
    with pytest.raises(SettingsError, match="at most"):
        store.update({"options": {"rt_min_critics_score": 150}})
    with pytest.raises(SettingsError, match="at least"):
        store.update({"options": {"max_items_per_run": 0}})
    with pytest.raises(SettingsError, match="must be a number"):
        store.update({"options": {"metacritic_min_score": "high"}})
