from datetime import date

from fresharr.config import Config
from fresharr.sources.tmdb import TmdbSource


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_source(**overrides) -> TmdbSource:
    cfg = Config(radarr_url="http://x", radarr_api_key="k", tmdb_api_key="key",
                 tmdb_tv=False)  # movies only keeps the assertions simple
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return TmdbSource(cfg)


def _capture(source, monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse({"results": [], "total_pages": 1})

    monkeypatch.setattr(source.session, "get", fake_get)
    source.fetch()
    return calls[0]


def test_recent_mode_uses_recent_window(monkeypatch):
    params = _capture(make_source(), monkeypatch)
    assert params["sort_by"] == "vote_average.desc"
    assert "primary_release_date.gte" in params  # a bounded recent window


def test_back_catalog_uses_min_year_floor_and_popularity_sort(monkeypatch):
    params = _capture(make_source(back_catalog=True, min_year=2020), monkeypatch)
    assert params["sort_by"] == "vote_count.desc"   # acclaimed, not obscure
    assert params["primary_release_date.gte"] == "2020-01-01"
    assert params["primary_release_date.lte"] == date.today().isoformat()


def test_back_catalog_without_min_year_has_no_lower_bound(monkeypatch):
    params = _capture(make_source(back_catalog=True, min_year=0), monkeypatch)
    assert "primary_release_date.gte" not in params  # all-time
    assert params["primary_release_date.lte"] == date.today().isoformat()
