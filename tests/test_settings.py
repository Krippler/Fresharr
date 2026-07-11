import json

import pytest

from fresharr.settings import SettingsError, SettingsStore

DEFAULTS = {"rottentomatoes": True, "imdb": False, "tmdb": False, "trakt": False}


def make_store(tmp_path) -> SettingsStore:
    return SettingsStore(str(tmp_path / "settings.json"), DEFAULTS)


def test_defaults(tmp_path):
    store = make_store(tmp_path)
    assert store.run_interval_days == 1.0
    assert store.is_enabled("rottentomatoes")
    assert not store.is_enabled("imdb")
    assert not store.is_enabled("nonexistent")


def test_update_persists_across_reload(tmp_path):
    store = make_store(tmp_path)
    store.update({"run_interval_days": 7,
                  "sources": {"imdb": {"enabled": True},
                              "rottentomatoes": {"enabled": False}}})

    reloaded = make_store(tmp_path)
    assert reloaded.run_interval_days == 7.0
    assert reloaded.is_enabled("imdb")
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
        store.update({"sources": {"imdbb": {"enabled": True}}})


def test_malformed_payloads_rejected(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(SettingsError):
        store.update({"run_interval_days": "soon"})
    with pytest.raises(SettingsError):
        store.update({"sources": {"imdb": {"enabled": "yes"}}})
    with pytest.raises(SettingsError):
        store.update(None)


def test_partial_update_leaves_rest_alone(tmp_path):
    store = make_store(tmp_path)
    store.update({"run_interval_days": 3})
    store.update({"sources": {"imdb": {"enabled": True}}})
    snapshot = store.snapshot()
    assert snapshot["run_interval_days"] == 3.0
    assert snapshot["sources"]["imdb"]["enabled"]
    assert snapshot["sources"]["rottentomatoes"]["enabled"]  # untouched default


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    (tmp_path / "settings.json").write_text("{oops")
    store = make_store(tmp_path)
    assert store.run_interval_days == 1.0
    assert store.is_enabled("rottentomatoes")
