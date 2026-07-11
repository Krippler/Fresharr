from fresharr.config import Config
from fresharr.models import MOVIE, TV
from fresharr.sources.trakt import TraktSource

TRENDING_MOVIES = [
    {"watchers": 120, "movie": {"title": "Dune: Part Two", "year": 2024,
                                "rating": 8.2,
                                "ids": {"trakt": 1, "slug": "dune-part-two-2024",
                                        "tmdb": 693134}}},
    {"watchers": 80, "movie": {"title": "Meh Movie", "year": 2026, "rating": 5.4,
                               "ids": {"trakt": 2, "slug": "meh", "tmdb": 2}}},
]

TRENDING_SHOWS = [
    {"watchers": 300, "show": {"title": "Great Show", "year": 2026, "rating": 8.9,
                               "ids": {"trakt": 3, "slug": "great-show", "tmdb": 3}}},
]


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_source() -> TraktSource:
    cfg = Config(radarr_url="http://x", radarr_api_key="k",
                 trakt_client_id="cid", trakt_min_rating=7.0)
    return TraktSource(cfg)


def test_fetch_trending(monkeypatch):
    source = make_source()

    def fake_get(url, params=None, timeout=None):
        return FakeResponse(TRENDING_MOVIES if "/movies/" in url else TRENDING_SHOWS)

    monkeypatch.setattr(source.session, "get", fake_get)
    items = source.fetch()
    assert [(i.title, i.media_type) for i in items] == [
        ("Dune: Part Two", MOVIE),  # Meh Movie filtered out by rating
        ("Great Show", TV),
    ]
    dune = items[0]
    assert dune.tmdb_id == 693134
    assert dune.audience_score == 82
    assert dune.url == "https://trakt.tv/movies/dune-part-two-2024"


def test_api_error_degrades_gracefully(monkeypatch):
    import requests
    source = make_source()

    def fake_get(url, params=None, timeout=None):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(source.session, "get", fake_get)
    assert source.fetch() == []
