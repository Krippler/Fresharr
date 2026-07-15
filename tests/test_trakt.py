from fresharr.config import Config
from fresharr.models import MOVIE, TV
from fresharr.sources.trakt import TraktSource

TRENDING_MOVIES = [
    {"watchers": 120, "movie": {"title": "Dune: Part Two", "year": 2024,
                                "rating": 8.2, "votes": 25000,
                                "ids": {"trakt": 1, "slug": "dune-part-two-2024",
                                        "tmdb": 693134}}},
    {"watchers": 80, "movie": {"title": "Meh Movie", "year": 2026, "rating": 5.4,
                               "votes": 900,
                               "ids": {"trakt": 2, "slug": "meh", "tmdb": 2}}},
    {"watchers": 60, "movie": {"title": "Tiny Sample", "year": 2026, "rating": 9.1,
                               "votes": 12,
                               "ids": {"trakt": 4, "slug": "tiny", "tmdb": 4}}},
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


def make_source(**overrides) -> TraktSource:
    cfg = Config(radarr_url="http://x", radarr_api_key="k",
                 trakt_client_id="cid",
                 trakt_min_rating_movies=7.0, trakt_min_rating_tv=7.0)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return TraktSource(cfg)


def test_fetch_trending(monkeypatch):
    source = make_source()

    def fake_get(url, params=None, timeout=None):
        return FakeResponse(TRENDING_MOVIES if "/movies/" in url else TRENDING_SHOWS)

    monkeypatch.setattr(source.session, "get", fake_get)
    items = source.fetch()
    assert [(i.title, i.media_type) for i in items] == [
        ("Dune: Part Two", MOVIE),  # Meh Movie filtered out by rating
        ("Tiny Sample", MOVIE),
        ("Great Show", TV),
    ]
    dune = items[0]
    assert dune.tmdb_id == 693134
    assert dune.audience_score == 82
    assert dune.votes == 25000
    assert dune.url == "https://trakt.tv/movies/dune-part-two-2024"


def test_movie_and_tv_use_separate_rating_thresholds(monkeypatch):
    # Movies need 9.0 (drops Dune 8.2, keeps Tiny 9.1); TV threshold 0 keeps
    # Great Show 8.9.
    source = make_source(trakt_min_rating_movies=9.0, trakt_min_rating_tv=0,
                         trakt_min_votes=0)

    def fake_get(url, params=None, timeout=None):
        return FakeResponse(TRENDING_MOVIES if "/movies/" in url else TRENDING_SHOWS)

    monkeypatch.setattr(source.session, "get", fake_get)
    items = source.fetch()
    assert [i.title for i in items] == ["Tiny Sample", "Great Show"]


def test_fetch_filters_by_votes(monkeypatch):
    source = make_source(trakt_min_votes=100)

    def fake_get(url, params=None, timeout=None):
        return FakeResponse(TRENDING_MOVIES if "/movies/" in url else TRENDING_SHOWS)

    monkeypatch.setattr(source.session, "get", fake_get)
    items = source.fetch()
    # Tiny Sample (12 votes) dropped; Great Show has no votes field -> kept?
    # No: shows fixture has no votes, (votes or 0) < 100 drops it.
    assert [i.title for i in items] == ["Dune: Part Two"]


def test_api_error_degrades_gracefully(monkeypatch):
    import requests
    source = make_source()

    def fake_get(url, params=None, timeout=None):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(source.session, "get", fake_get)
    assert source.fetch() == []


def test_sends_named_user_agent():
    # A named User-Agent is what gets past Cloudflare in front of the API.
    source = make_source()
    assert source.session.headers["User-Agent"].startswith("Fresharr/")
    assert source.session.headers["trakt-api-key"] == "cid"


def test_forbidden_gives_client_id_hint(monkeypatch, caplog):
    import requests
    source = make_source()

    class Forbidden:
        status_code = 403

        def raise_for_status(self):
            err = requests.HTTPError("403 Client Error: Forbidden")
            err.response = self
            raise err

        def json(self):
            return {}

    monkeypatch.setattr(source.session, "get",
                        lambda url, params=None, timeout=None: Forbidden())
    with caplog.at_level("WARNING"):
        assert source.fetch() == []
    assert any("Client ID" in r.message for r in caplog.records)
