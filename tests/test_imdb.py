import json

from fresharr.config import Config
from fresharr.models import MOVIE
from fresharr.sources.imdb import ImdbSource, parse_ld_json, parse_next_data

NEXT_DATA = {
    "props": {"pageProps": {"pageData": {"chartTitles": {"edges": [
        {"node": {
            "id": "tt15239678",
            "titleText": {"text": "Dune: Part Two"},
            "releaseYear": {"year": 2024},
            "ratingsSummary": {"aggregateRating": 8.5, "voteCount": 500000},
        }},
        {"node": {
            "id": "tt0000009",
            "titleText": {"text": "Obscure Gem"},
            "releaseYear": {"year": 2026},
            "ratingsSummary": {"aggregateRating": 8.9, "voteCount": 40},
        }},
        {"node": {
            "id": "tt0000001",
            "titleText": {"text": "Mediocre Movie"},
            "releaseYear": {"year": 2026},
            "ratingsSummary": {"aggregateRating": 5.1},
        }},
        {"node": {
            "id": "tt0000002",
            "titleText": {"text": "Not Yet Rated"},
            "releaseYear": {"year": 2026},
            "ratingsSummary": {"aggregateRating": None},
        }},
    ]}}}}
}

NEXT_HTML = ('<html><script id="__NEXT_DATA__" type="application/json">'
             + json.dumps(NEXT_DATA) + "</script></html>")

LD_HTML = """<html><script type="application/ld+json">
{"itemListElement": [
  {"item": {"name": "Chart Film", "url": "https://www.imdb.com/title/tt1/",
            "aggregateRating": {"ratingValue": 8.1}}}
]}
</script></html>"""


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def make_source(**overrides) -> ImdbSource:
    cfg = Config(radarr_url="http://x", radarr_api_key="k")
    cfg.imdb_movie_charts = ["moviemeter"]
    cfg.imdb_tv_charts = []
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return ImdbSource(cfg)


def test_parse_next_data_extracts_titles():
    items = parse_next_data(NEXT_HTML, MOVIE, "imdb")
    assert [i.title for i in items] == ["Dune: Part Two", "Obscure Gem",
                                        "Mediocre Movie", "Not Yet Rated"]
    dune = items[0]
    assert dune.year == 2024
    assert dune.audience_score == 85
    assert dune.votes == 500000
    assert dune.url == "https://www.imdb.com/title/tt15239678/"
    assert items[3].audience_score is None


def test_fetch_filters_by_rating(monkeypatch):
    source = make_source(imdb_min_rating=7.0)
    monkeypatch.setattr(source.session, "get",
                        lambda url, timeout=None: FakeResponse(NEXT_HTML))
    items = source.fetch()
    assert [i.title for i in items] == ["Dune: Part Two", "Obscure Gem"]


def test_fetch_filters_by_votes(monkeypatch):
    source = make_source(imdb_min_rating=7.0, imdb_min_votes=1000)
    monkeypatch.setattr(source.session, "get",
                        lambda url, timeout=None: FakeResponse(NEXT_HTML))
    items = source.fetch()
    assert [i.title for i in items] == ["Dune: Part Two"]  # Obscure Gem: 40 votes


def test_ld_json_fallback(monkeypatch):
    source = make_source(imdb_min_rating=7.0)
    monkeypatch.setattr(source.session, "get",
                        lambda url, timeout=None: FakeResponse(LD_HTML))
    items = source.fetch()
    assert [i.title for i in items] == ["Chart Film"]
    assert items[0].audience_score == 81


def test_parse_ld_json_direct():
    items = parse_ld_json(LD_HTML, MOVIE, "imdb")
    assert len(items) == 1


def test_layout_change_degrades_gracefully(monkeypatch):
    source = make_source()
    monkeypatch.setattr(source.session, "get",
                        lambda url, timeout=None: FakeResponse("<html>redesign!</html>"))
    assert source.fetch() == []
