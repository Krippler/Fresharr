from fresharr.config import Config
from fresharr.models import MOVIE, TV, MediaItem
from fresharr.runner import collect_items


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
    def __init__(self, languages=(), anime_languages=()):
        self.languages = list(languages)
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
    MediaItem(title="Japanese Anime", media_type=TV, source="anilist",
              year=2026, language="ja", anime=True),
    MediaItem(title="Chinese Donghua", media_type=TV, source="anilist",
              year=2026, language="zh", anime=True),
]


def test_language_filter_split_by_anime(monkeypatch):
    settings = FakeSettings(languages=["en"], anime_languages=["ja"])
    result = run_collect_with_settings(monkeypatch, settings, LANG_ITEMS)
    # French movie dropped (movies list), Chinese donghua dropped (anime
    # list), unknown-language item passes.
    assert sorted(i.title for i in result) == [
        "English Movie", "Japanese Anime", "Unknown Language Movie"]


def test_empty_language_lists_pass_everything(monkeypatch):
    settings = FakeSettings()
    result = run_collect_with_settings(monkeypatch, settings, LANG_ITEMS)
    assert len(result) == len(LANG_ITEMS)


def test_anime_filter_does_not_touch_movies(monkeypatch):
    settings = FakeSettings(anime_languages=["ja"])
    result = run_collect_with_settings(monkeypatch, settings, LANG_ITEMS)
    assert sorted(i.title for i in result) == [
        "English Movie", "French Movie", "Japanese Anime",
        "Unknown Language Movie"]
