from fresharr.config import Config
from fresharr.models import MOVIE, TV
from fresharr.sources.anilist import AniListSource

ANILIST_RESPONSE = {
    "data": {"Page": {"media": [
        {"id": 101, "format": "TV", "averageScore": 88, "seasonYear": 2026,
         "title": {"romaji": "Sousou no Frieren", "english": "Frieren: Beyond Journey's End"},
         "startDate": {"year": 2026}},
        {"id": 102, "format": "MOVIE", "averageScore": 90, "seasonYear": None,
         "title": {"romaji": "Kimi no Na wa.", "english": "Your Name."},
         "startDate": {"year": 2026}},
        {"id": 103, "format": "TV", "averageScore": 55, "seasonYear": 2026,
         "title": {"romaji": "Mediocre Isekai", "english": None},
         "startDate": {"year": 2026}},
        {"id": 104, "format": "OVA", "averageScore": 92, "seasonYear": 2026,
         "title": {"romaji": "Some OVA", "english": None},
         "startDate": {"year": 2026}},
        {"id": 105, "format": "TV", "averageScore": None, "seasonYear": 2026,
         "title": {"romaji": "Unrated Show", "english": None},
         "startDate": {"year": 2026}},
    ]}}
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_source() -> AniListSource:
    cfg = Config(radarr_url="http://x", radarr_api_key="k")
    return AniListSource(cfg)


def test_fetch_trending_anime(monkeypatch):
    source = make_source()
    monkeypatch.setattr(source.session, "post",
                        lambda url, json=None, timeout=None: FakeResponse(ANILIST_RESPONSE))
    items = source.fetch()
    # Score >= 75 keeps Frieren + Your Name; OVA skipped; unrated skipped
    assert [(i.title, i.media_type) for i in items] == [
        ("Frieren: Beyond Journey's End", TV),
        ("Your Name.", MOVIE),
    ]
    frieren = items[0]
    assert frieren.anime is True
    assert frieren.alt_titles == ("Sousou no Frieren",)
    assert frieren.audience_score == 88
    assert frieren.year == 2026
    assert frieren.url == "https://anilist.co/anime/101"


def test_romaji_used_when_no_english_title(monkeypatch):
    payload = {"data": {"Page": {"media": [
        {"id": 1, "format": "TV", "averageScore": 80, "seasonYear": 2026,
         "title": {"romaji": "Romaji Only", "english": None},
         "startDate": {"year": 2026}},
    ]}}}
    source = make_source()
    monkeypatch.setattr(source.session, "post",
                        lambda url, json=None, timeout=None: FakeResponse(payload))
    items = source.fetch()
    assert items[0].title == "Romaji Only"
    assert items[0].alt_titles == ()


def test_back_catalog_uses_score_sort_and_year_floor(monkeypatch):
    cfg = Config(radarr_url="http://x", radarr_api_key="k",
                 back_catalog=True, min_year=2020)
    source = AniListSource(cfg)
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured.update(json or {})
        return FakeResponse(ANILIST_RESPONSE)

    monkeypatch.setattr(source.session, "post", fake_post)
    source.fetch()
    assert "SCORE_DESC" in captured["query"]
    assert "TRENDING_DESC" not in captured["query"]
    assert captured["variables"]["start"] == 20200000  # FuzzyDateInt for 2020


def test_api_change_degrades_gracefully(monkeypatch):
    source = make_source()
    monkeypatch.setattr(source.session, "post",
                        lambda url, json=None, timeout=None: FakeResponse({"errors": ["nope"]}))
    assert source.fetch() == []
