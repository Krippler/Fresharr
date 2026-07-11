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
    cfg = Config(sources=[], radarr_url="http://x", radarr_api_key="k",
                 sonarr_url="http://y", sonarr_api_key="k")
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def run_collect(monkeypatch, config, items):
    monkeypatch.setattr("fresharr.runner.build_sources",
                        lambda cfg: [FakeSource(items)])
    return collect_items(config)


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
