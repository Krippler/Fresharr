import requests

from fresharr.config import Config
from fresharr.models import MOVIE, TV, MediaItem
from fresharr.runner import collect_items, run_once
from fresharr.settings import SettingsStore
from fresharr.sources import SOURCE_DEFAULTS


class FakeSource:
    name = "fake"

    def __init__(self, items):
        self._items = items

    def fetch(self):
        return self._items


def make_config(**overrides) -> Config:
    cfg = Config(radarr_url="http://x", radarr_api_key="k",
                 sonarr_url="http://y", sonarr_api_key="k")
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def run_collect(monkeypatch, config, items):
    monkeypatch.setattr("fresharr.runner.build_sources",
                        lambda cfg, settings: [FakeSource(items)])
    return collect_items(config, settings=None)


def test_dedupes_same_title_across_sources(monkeypatch):
    items = [
        MediaItem(title="Dune: Part Two", media_type=MOVIE, source="rottentomatoes", year=2024),
        MediaItem(title="Dune Part Two", media_type=MOVIE, source="tmdb", year=2024, tmdb_id=693134),
    ]
    result = run_collect(monkeypatch, make_config(), items)
    assert len(result) == 1
    assert result[0].tmdb_id == 693134  # duplicate with TMDB id wins


def test_min_year_filter(monkeypatch):
    items = [
        MediaItem(title="Old", media_type=MOVIE, source="s", year=1998),
        MediaItem(title="New", media_type=MOVIE, source="s", year=2026),
        MediaItem(title="Unknown Year", media_type=MOVIE, source="s", year=None),
    ]
    result = run_collect(monkeypatch, make_config(min_year=2020), items)
    assert sorted(i.title for i in result) == ["New", "Unknown Year"]


def test_tv_dropped_without_sonarr(monkeypatch):
    items = [
        MediaItem(title="A Movie", media_type=MOVIE, source="s", year=2026),
        MediaItem(title="A Show", media_type=TV, source="s", year=2026),
    ]
    config = make_config(sonarr_url="", sonarr_api_key="")
    result = run_collect(monkeypatch, config, items)
    assert [i.title for i in result] == ["A Movie"]


class FakeSettings:
    def __init__(self, movie_languages=(), tv_languages=(), anime_languages=()):
        self.movie_languages = list(movie_languages)
        self.tv_languages = list(tv_languages)
        self.anime_languages = list(anime_languages)


def run_collect_with_settings(monkeypatch, settings, items):
    monkeypatch.setattr("fresharr.runner.build_sources",
                        lambda cfg, s: [FakeSource(items)])
    return collect_items(make_config(), settings)


LANG_ITEMS = [
    MediaItem(title="English Movie", media_type=MOVIE, source="tmdb",
              year=2026, language="en"),
    MediaItem(title="French Movie", media_type=MOVIE, source="tmdb",
              year=2026, language="fr"),
    MediaItem(title="Unknown Language Movie", media_type=MOVIE,
              source="rottentomatoes", year=2026),
    MediaItem(title="Korean Show", media_type=TV, source="tmdb",
              year=2026, language="ko"),
    MediaItem(title="English Show", media_type=TV, source="tmdb",
              year=2026, language="en"),
    MediaItem(title="Japanese Anime", media_type=TV, source="anilist",
              year=2026, language="ja", anime=True),
    MediaItem(title="Chinese Donghua", media_type=TV, source="anilist",
              year=2026, language="zh", anime=True),
]


def test_language_filters_split_by_movie_tv_anime(monkeypatch):
    settings = FakeSettings(movie_languages=["en"], tv_languages=["ko"],
                            anime_languages=["ja"])
    result = run_collect_with_settings(monkeypatch, settings, LANG_ITEMS)
    # French movie dropped (movie list), English show dropped (tv list),
    # Chinese donghua dropped (anime list), unknown-language item passes.
    assert sorted(i.title for i in result) == [
        "English Movie", "Japanese Anime", "Korean Show",
        "Unknown Language Movie"]


def test_empty_language_lists_pass_everything(monkeypatch):
    settings = FakeSettings()
    result = run_collect_with_settings(monkeypatch, settings, LANG_ITEMS)
    assert len(result) == len(LANG_ITEMS)


def test_each_language_list_is_independent(monkeypatch):
    # Only the anime list set: movies and TV are untouched
    settings = FakeSettings(anime_languages=["ja"])
    result = run_collect_with_settings(monkeypatch, settings, LANG_ITEMS)
    assert "Chinese Donghua" not in {i.title for i in result}
    assert len(result) == len(LANG_ITEMS) - 1

    # Only the movie list set: TV shows and anime are untouched
    settings = FakeSettings(movie_languages=["en"])
    result = run_collect_with_settings(monkeypatch, settings, LANG_ITEMS)
    assert "French Movie" not in {i.title for i in result}
    assert len(result) == len(LANG_ITEMS) - 1


def make_run_config(tmp_path, **overrides) -> Config:
    cfg = Config(radarr_url="http://x", radarr_api_key="k",
                 state_file=str(tmp_path / "state.json"),
                 status_file=str(tmp_path / "status.json"),
                 settings_file=str(tmp_path / "settings.json"))
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def make_movies(n) -> list[MediaItem]:
    return [MediaItem(title=f"Movie {i}", media_type=MOVIE, source="s", year=2026)
            for i in range(n)]


def test_stalled_arr_deferred_after_repeated_timeouts(tmp_path, monkeypatch):
    monkeypatch.setattr("fresharr.runner.build_sources",
                        lambda cfg, s: [FakeSource(make_movies(8))])

    class StalledRadarr:
        app_name = "Radarr"

        def __init__(self, config):
            self.add_calls = 0

        def check_connection(self):
            pass

        def load_library(self):
            pass

        def add(self, item):
            self.add_calls += 1
            raise requests.ReadTimeout("read timed out")

    created = []
    monkeypatch.setattr("fresharr.runner.Radarr",
                        lambda config: created.append(StalledRadarr(config)) or created[-1])
    config = make_run_config(tmp_path, sonarr_url="", sonarr_api_key="")
    settings = SettingsStore(config.settings_file, SOURCE_DEFAULTS)

    summary = run_once(config, settings)
    # Stops after 3 consecutive failures instead of hammering all 8 items.
    assert created[0].add_calls == 3
    assert summary["counts"]["failed"] == 3
    assert summary["counts"]["skipped"] == 5
    assert "stopped responding" in (summary["error"] or "")


def test_arr_whose_library_wont_load_is_deferred(tmp_path, monkeypatch):
    monkeypatch.setattr("fresharr.runner.build_sources",
                        lambda cfg, s: [FakeSource(make_movies(4))])

    class UnreachableRadarr:
        app_name = "Radarr"

        def __init__(self, config):
            self.add_calls = 0

        def check_connection(self):
            pass

        def load_library(self):
            raise requests.ConnectionError("connection refused")

        def add(self, item):  # pragma: no cover - should never be called
            self.add_calls += 1
            raise AssertionError("add() should not run for a deferred client")

    created = []
    monkeypatch.setattr("fresharr.runner.Radarr",
                        lambda config: created.append(UnreachableRadarr(config)) or created[-1])
    config = make_run_config(tmp_path, sonarr_url="", sonarr_api_key="")
    settings = SettingsStore(config.settings_file, SOURCE_DEFAULTS)

    summary = run_once(config, settings)
    assert created[0].add_calls == 0            # never tried to add
    assert summary["counts"]["added"] == 0
    assert "not responding" in (summary["error"] or "")
