from fresharr.config import Config
from fresharr.sources.letterboxd import LetterboxdSource, _extract_ld_json

LIST_HTML = """
<ul>
  <li class="listitem"><div class="film-poster" data-film-slug="the-substance"></div></li>
  <li class="listitem"><div class="film-poster" data-film-slug="mediocre-movie"></div></li>
  <li class="listitem"><div class="film-poster" data-film-slug="the-substance"></div></li>
</ul>
"""

FILM_PAGES = {
    "the-substance": """
<script type="application/ld+json">
/* <![CDATA[ */
{"@type": "Movie", "name": "The Substance",
 "releasedEvent": [{"@type": "PublicationEvent", "startDate": "2024"}],
 "aggregateRating": {"ratingValue": 4.02, "ratingCount": 12345}}
/* ]]> */
</script>
""",
    "mediocre-movie": """
<script type="application/ld+json">
{"@type": "Movie", "name": "Mediocre Movie",
 "releasedEvent": [{"@type": "PublicationEvent", "startDate": "2026"}],
 "aggregateRating": {"ratingValue": 2.4, "ratingCount": 100}}
</script>
""",
}


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def make_source(**overrides) -> LetterboxdSource:
    cfg = Config(radarr_url="http://x", radarr_api_key="k")
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return LetterboxdSource(cfg)


def fake_get(url, timeout=None):
    if "/films/" in url and "/film/" not in url:
        return FakeResponse(LIST_HTML)
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return FakeResponse(FILM_PAGES.get(slug, "<html></html>"))


def test_fetch_popular_films(monkeypatch):
    source = make_source(letterboxd_min_rating=3.5)
    monkeypatch.setattr(source.session, "get", fake_get)
    items = source.fetch()
    assert [i.title for i in items] == ["The Substance"]  # 2.4 stars filtered out
    film = items[0]
    assert film.year == 2024
    assert film.audience_score == 80  # 4.02 stars -> 80/100
    assert film.url == "https://letterboxd.com/film/the-substance/"


def test_min_reviews_filter(monkeypatch):
    # The Substance has 12345 ratings, Mediocre Movie has 100
    source = make_source(letterboxd_min_rating=0, letterboxd_min_reviews=1000)
    monkeypatch.setattr(source.session, "get", fake_get)
    items = source.fetch()
    assert [i.title for i in items] == ["The Substance"]
    assert items[0].votes == 12345


def test_max_films_cap(monkeypatch):
    source = make_source(letterboxd_min_rating=0, letterboxd_max_films=1)
    calls = []

    def counting_get(url, timeout=None):
        calls.append(url)
        return fake_get(url)

    monkeypatch.setattr(source.session, "get", counting_get)
    source.fetch()
    # 1 list request + 1 film request (cap), despite 2 unique slugs
    assert len(calls) == 2


def test_cdata_wrapper_stripped():
    data = _extract_ld_json(FILM_PAGES["the-substance"])
    assert data["name"] == "The Substance"


def test_layout_change_degrades_gracefully(monkeypatch):
    source = make_source()
    monkeypatch.setattr(source.session, "get",
                        lambda url, timeout=None: FakeResponse("<html>redesign</html>"))
    assert source.fetch() == []
