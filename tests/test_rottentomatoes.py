from fresharr.config import Config
from fresharr.models import MOVIE, TV
from fresharr.sources.rottentomatoes import (
    RottenTomatoesSource,
    parse_browse_html,
)

# Representative of the rendered browse-page tile markup: an anchor per
# title carrying scores as attributes and the title/date in data-qa spans.
BROWSE_HTML = """
<div class="discovery-tiles">
  <a data-track="scores" href="/m/dune_part_two" class="js-tile-link">
    <score-pairs-deprecated criticsscore="92" audiencescore="95"
      state="certified-fresh"></score-pairs-deprecated>
    <span data-qa="discovery-media-list-item-title" class="p--small">Dune: Part Two</span>
    <span data-qa="discovery-media-list-item-start-date">Streaming Mar 26, 2024</span>
  </a>
  <a data-track="scores" href="/m/low_rated_flick" class="js-tile-link">
    <score-pairs-deprecated criticsscore="41" audiencescore="38"></score-pairs-deprecated>
    <span data-qa="discovery-media-list-item-title" class="p--small">Low Rated Flick</span>
    <span data-qa="discovery-media-list-item-start-date">In theaters Jan 5, 2024</span>
  </a>
  <a data-track="scores" href="/m/no_scores_yet" class="js-tile-link">
    <score-pairs-deprecated></score-pairs-deprecated>
    <span data-qa="discovery-media-list-item-title" class="p--small">No Scores Yet</span>
    <span data-qa="discovery-media-list-item-start-date">Coming soon</span>
  </a>
</div>
"""


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def make_config(**overrides) -> Config:
    cfg = Config(radarr_url="http://x", radarr_api_key="k")
    cfg.rt_movie_lists = ["movies_in_theaters/critics:certified_fresh"]
    cfg.rt_tv_lists = []
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_parse_browse_html():
    items = parse_browse_html(BROWSE_HTML, MOVIE, "rottentomatoes")
    assert [i.title for i in items] == ["Dune: Part Two", "Low Rated Flick",
                                        "No Scores Yet"]
    dune = items[0]
    assert dune.media_type == MOVIE
    assert dune.year == 2024
    assert dune.critics_score == 92
    assert dune.audience_score == 95
    assert dune.url == "https://www.rottentomatoes.com/m/dune_part_two"
    assert items[2].critics_score is None


def test_fetch_filters_by_critics_score(monkeypatch):
    source = RottenTomatoesSource(make_config(rt_min_critics_score=80))
    monkeypatch.setattr(source.session, "get",
                        lambda url, timeout=None: FakeResponse(BROWSE_HTML))
    items = source.fetch()
    assert [i.title for i in items] == ["Dune: Part Two"]


def test_fetch_no_thresholds_keeps_all(monkeypatch):
    source = RottenTomatoesSource(
        make_config(rt_min_critics_score=0, rt_min_audience_score=0))
    monkeypatch.setattr(source.session, "get",
                        lambda url, timeout=None: FakeResponse(BROWSE_HTML))
    assert len(source.fetch()) == 3


def test_fetch_survives_layout_change(monkeypatch):
    source = RottenTomatoesSource(make_config())
    monkeypatch.setattr(source.session, "get",
                        lambda url, timeout=None: FakeResponse("<html>redesign</html>"))
    assert source.fetch() == []


def test_tv_list_uses_tv_media_type():
    html = ('<a href="/tv/the_studio">'
            '<score-pairs-deprecated criticsscore="95"></score-pairs-deprecated>'
            '<span data-qa="discovery-media-list-item-title">The Studio</span></a>')
    items = parse_browse_html(html, TV, "rottentomatoes")
    assert items[0].media_type == TV
    assert items[0].url == "https://www.rottentomatoes.com/tv/the_studio"
