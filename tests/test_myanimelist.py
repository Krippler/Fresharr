from fresharr.config import Config
from fresharr.models import MOVIE, TV
from fresharr.sources.myanimelist import MyAnimeListSource

SEASON_NOW = {"data": [
    {"mal_id": 1, "type": "TV", "score": 8.8, "year": 2026,
     "title": "Sousou no Frieren", "title_english": "Frieren: Beyond Journey's End",
     "url": "https://myanimelist.net/anime/1"},
    {"mal_id": 2, "type": "TV", "score": 5.9, "year": 2026,
     "title": "Weak Show", "title_english": None,
     "url": "https://myanimelist.net/anime/2"},
    {"mal_id": 3, "type": "Special", "score": 9.0, "year": 2026,
     "title": "A Special", "title_english": None,
     "url": "https://myanimelist.net/anime/3"},
]}

TOP_AIRING = {"data": [
    # Duplicate of mal_id 1 - must be deduped
    {"mal_id": 1, "type": "TV", "score": 8.8, "year": 2026,
     "title": "Sousou no Frieren", "title_english": "Frieren: Beyond Journey's End",
     "url": "https://myanimelist.net/anime/1"},
    {"mal_id": 4, "type": "Movie", "score": 8.1, "year": None,
     "aired": {"prop": {"from": {"year": 2026}}},
     "title": "Great Anime Film", "title_english": None,
     "url": "https://myanimelist.net/anime/4"},
]}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_dedupes_and_filters(monkeypatch):
    cfg = Config(radarr_url="http://x", radarr_api_key="k")
    source = MyAnimeListSource(cfg)

    def fake_get(url, timeout=None):
        return FakeResponse(SEASON_NOW if "/seasons/now" in url else TOP_AIRING)

    monkeypatch.setattr(source.session, "get", fake_get)
    items = source.fetch()
    # Frieren once (deduped), Weak Show filtered (5.9 < 7.5), Special skipped,
    # movie kept with year from aired fallback
    assert [(i.title, i.media_type) for i in items] == [
        ("Frieren: Beyond Journey's End", TV),
        ("Great Anime Film", MOVIE),
    ]
    frieren = items[0]
    assert frieren.anime is True
    assert frieren.alt_titles == ("Sousou no Frieren",)
    assert frieren.audience_score == 88
    assert items[1].year == 2026
