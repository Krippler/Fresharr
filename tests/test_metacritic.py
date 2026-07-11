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
