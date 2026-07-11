from fresharr.config import Config
from fresharr.models import MOVIE, TV
from fresharr.sources.metacritic import MetacriticSource, parse_browse_html

BROWSE_HTML = """
<div class="c-finderProductCard c-finderProductCard-game">
  <a href="/movie/dune-part-two/" data-title="Dune: Part Two">
    <span class="u-text-uppercase">Mar 1, 2024</span>
    <div class="c-siteReviewScore" title="Metascore 93 out of 100"><span>93</span></div>
  </a>
</div>
<div class="c-finderProductCard c-finderProductCard-game">
  <a href="/movie/weak-flick/" data-title="Weak &amp; Flick">
    <span class="u-text-uppercase">Jan 5, 2026</span>
    <div class="c-siteReviewScore" title="Metascore 44 out of 100"><span>44</span></div>
  </a>
</div>
<div class="c-finderProductCard c-finderProductCard-game">
  <a href="/movie/no-score-yet/" data-title="No Score Yet">
    <span class="u-text-uppercase">Jun 1, 2026</span>
  </a>
</div>
"""


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_parse_browse_html():
    items = parse_browse_html(BROWSE_HTML, MOVIE, "metacritic")
    assert [i.title for i in items] == ["Dune: Part Two", "Weak & Flick", "No Score Yet"]
    dune = items[0]
    assert dune.critics_score == 93
    assert dune.year == 2024
    assert items[2].critics_score is None


def test_fetch_filters_by_metascore(monkeypatch):
    cfg = Config(radarr_url="http://x", radarr_api_key="k")
    source = MetacriticSource(cfg)

    def fake_get(url, params=None, timeout=None):
        return FakeResponse(BROWSE_HTML if "/browse/movie/" in url else "<html></html>")

    monkeypatch.setattr(source.session, "get", fake_get)
    items = source.fetch()
    assert [(i.title, i.media_type) for i in items] == [("Dune: Part Two", MOVIE)]


def test_layout_change_degrades_gracefully():
    assert parse_browse_html("<html>redesign</html>", TV, "metacritic") == []


def test_year_from_release_date_not_slug():
    # Regression: "2000 Meters to Andriivka" must not take 2000 from its
    # URL slug; the release date wins.
    html = ('<div data-title="2000 Meters to Andriivka">'
            '<a href="/movie/2000-meters-to-andriivka/"></a>'
            '<span>Sep 19, 2025</span>'
            '<div title="Metascore 88 out of 100">88</div></div>')
    item = parse_browse_html(html, MOVIE, "metacritic")[0]
    assert item.title == "2000 Meters to Andriivka"
    assert item.year == 2025


def test_year_stripped_from_title():
    # Regression: "Forever (2025)" must not render as "Forever (2025) (2025)".
    html = ('<div data-title="Forever (2025)">'
            '<span>May 8, 2025</span>'
            '<div title="Metascore 84 out of 100">84</div></div>')
    item = parse_browse_html(html, TV, "metacritic")[0]
    assert item.title == "Forever"
    assert item.year == 2025


def test_title_year_used_when_no_release_date():
    html = ('<div data-title="The Muppet Show (2026)">'
            '<div title="Metascore 81 out of 100">81</div></div>')
    item = parse_browse_html(html, TV, "metacritic")[0]
    assert item.title == "The Muppet Show"
    assert item.year == 2026
