from fresharr.config import Config
from fresharr.models import MOVIE
from fresharr.sources.rottentomatoes import RottenTomatoesSource, _extract_year, _score

RT_PAGE = {
    "grid": {
        "list": [
            {
                "title": "Dune: Part Two",
                "mediaUrl": "/m/dune_part_two",
                "releaseDateText": "Streaming Mar 26, 2024",
                "criticsScore": {"score": "92", "certifiedAttribute": "certified-fresh"},
                "audienceScore": {"score": "95"},
            },
            {
                "title": "Low Rated Flick",
                "mediaUrl": "/m/low_rated",
                "releaseDateText": "In theaters Jan 5, 2024",
                "criticsScore": {"score": "41"},
                "audienceScore": {"score": "38"},
            },
            {
                "title": "No Scores Yet",
                "mediaUrl": "/m/no_scores",
                "releaseDateText": "In theaters Jun 1, 2024",
                "criticsScore": {},
                "audienceScore": {},
            },
        ]
    },
    "pageInfo": {"hasNextPage": False, "endCursor": ""},
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_config(**overrides) -> Config:
    cfg = Config(sources=["rottentomatoes"], radarr_url="http://x", radarr_api_key="k")
    cfg.rt_movie_lists = ["movies_in_theaters/critics:certified_fresh"]
    cfg.rt_tv_lists = []
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_fetch_filters_by_critics_score(monkeypatch):
    source = RottenTomatoesSource(make_config(rt_min_critics_score=80))
    monkeypatch.setattr(source.session, "get",
                        lambda url, params=None, timeout=None: FakeResponse(RT_PAGE))
    items = source.fetch()
    assert [i.title for i in items] == ["Dune: Part Two"]
    item = items[0]
    assert item.media_type == MOVIE
    assert item.year == 2024
    assert item.critics_score == 92
    assert item.audience_score == 95
    assert item.url == "https://www.rottentomatoes.com/m/dune_part_two"


def test_fetch_no_thresholds_keeps_unscored(monkeypatch):
    source = RottenTomatoesSource(
        make_config(rt_min_critics_score=0, rt_min_audience_score=0))
    monkeypatch.setattr(source.session, "get",
                        lambda url, params=None, timeout=None: FakeResponse(RT_PAGE))
    assert len(source.fetch()) == 3


def test_fetch_survives_schema_change(monkeypatch):
    source = RottenTomatoesSource(make_config())
    monkeypatch.setattr(source.session, "get",
                        lambda url, params=None, timeout=None: FakeResponse({"unexpected": True}))
    assert source.fetch() == []


def test_score_parsing():
    assert _score({"score": "93"}) == 93
    assert _score({"score": 88}) == 88
    assert _score("77") == 77
    assert _score({"score": ""}) is None
    assert _score({}) is None
    assert _score(None) is None
    assert _score({"score": "n/a"}) is None


def test_year_extraction():
    assert _extract_year({"releaseDateText": "Streaming Mar 26, 2024"}) == 2024
    assert _extract_year({"publicReleaseDate": "1999-10-15"}) == 1999
    assert _extract_year({"releaseDateText": "Coming soon"}) is None
    assert _extract_year({}) is None
