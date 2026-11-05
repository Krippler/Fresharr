import time

import pytest

from fresharr import state as state_mod
from fresharr.config import Config
from fresharr.filters import Rules, canonical_genres, rules_for, tmdb_genre_names
from fresharr.models import MOVIE, TV, MediaItem
from fresharr.runner import collect_items
from fresharr.settings import SettingsError, SettingsStore
from fresharr.sources import SOURCE_DEFAULTS
from fresharr.sources.anilist import AniListSource
from fresharr.sources.tmdb import TmdbSource
from fresharr.sources.trakt import TraktSource
from fresharr.state import State

from test_sonarr import make_sonarr


# ── Name matching ────────────────────────────────────────────────────────────

def test_genre_spellings_from_every_site_match_one_id():
    assert canonical_genres(["Action & Adventure"]) == {"action", "adventure"}
    assert canonical_genres(["Sci-Fi & Fantasy"]) == {"science-fiction", "fantasy"}
    assert canonical_genres(["science-fiction"]) == {"science-fiction"}   # Trakt
    assert canonical_genres(["Science Fiction"]) == {"science-fiction"}   # Radarr
    assert canonical_genres(["Sci-Fi"]) == {"science-fiction"}            # AniList
    assert canonical_genres(["Children"]) == {"kids"}                     # Sonarr
    assert canonical_genres(["talk-show"]) == {"talk"}
    assert canonical_genres(["Slice of Life"]) == {"slice-of-life"}
    assert canonical_genres(["TV Movie", None, 7]) == set()               # unknown


def test_tmdb_genre_ids_are_named():
    assert tmdb_genre_names([99, 18], MOVIE) == ("documentary", "drama")
    assert tmdb_genre_names([10765], TV) == ("fantasy", "science-fiction")


def test_genre_include_and_exclude():
    rules = Rules(include_genres=frozenset({"comedy", "documentary"}),
                  exclude_genres=frozenset({"reality"}))
    assert rules.genre_reason(["Comedy", "Drama"]) is None        # any one is enough
    assert "not in the selected" in rules.genre_reason(["Drama"])
    assert "excluded" in rules.genre_reason(["Documentary", "Reality"])  # exclude wins
    assert rules.genre_reason([]) is None                         # unknown passes


def test_network_matching_handles_brand_spellings():
    rules = Rules(include_networks=("hbo", "disney-plus", "fx"))
    assert rules.network_reason("HBO") is None
    assert rules.network_reason("Disney+") is None
    assert rules.network_reason("FX (US)") is None                # country tag dropped
    assert "not in the selected" in rules.network_reason("HBO Max")  # a different network
    assert rules.network_reason(None) is None                     # unknown passes

    both = Rules(include_networks=("max",))
    assert both.network_reason("HBO Max") is None
    assert both.network_reason("Max") is None
    assert Rules(include_networks=("prime-video",)).network_reason("Amazon") is None


def test_typed_in_network_names_match():
    rules = Rules(exclude_networks=("BBC Three",))
    assert "excluded" in rules.network_reason("BBC Three")
    assert "excluded" in rules.network_reason("bbc three")
    assert rules.network_reason("BBC One") is None


def test_signature_changes_with_the_filters():
    a = Rules(exclude_genres=frozenset({"reality"}))
    assert a.signature() == Rules(exclude_genres=frozenset({"reality"})).signature()
    assert a.signature() != Rules(exclude_genres=frozenset({"news"})).signature()
    assert a.signature() != Rules().signature()


# ── Pushing filters into the sites' searches ────────────────────────────────

def test_tmdb_params():
    docs = Rules(include_genres=frozenset({"documentary"}))
    assert docs.tmdb_params(MOVIE, series=False) == {"with_genres": "99"}

    # TMDB has no TV "history" genre: nothing is pushed rather than losing titles.
    assert Rules(include_genres=frozenset({"history"})).tmdb_params(TV, True) == {}

    # Excluding fantasy alone mustn't exclude TMDB's "Sci-Fi & Fantasy".
    assert Rules(exclude_genres=frozenset({"fantasy"})).tmdb_params(TV, True) == {}
    both = Rules(exclude_genres=frozenset({"fantasy", "science-fiction"}))
    assert both.tmdb_params(TV, True) == {"without_genres": "10765"}
    # "War & Politics" is also politics, which can't be selected.
    assert Rules(exclude_genres=frozenset({"war"})).tmdb_params(TV, True) == {}

    nets = Rules(include_networks=("netflix", "hbo"))
    assert nets.tmdb_params(TV, series=True) == {"with_networks": "49|213"}
    assert nets.tmdb_params(MOVIE, series=False) == {}
    assert Rules(include_networks=("BBC Three",)).tmdb_params(TV, True) == {}


def test_trakt_and_anilist_params():
    rules = Rules(include_genres=frozenset({"kids", "talk"}),
                  exclude_genres=frozenset({"ecchi"}))
    assert rules.trakt_params() == {"genres": "children,talk-show"}
    assert rules.anilist_variables() == {"genreNotIn": ["Ecchi"]}  # kids/talk: no AniList genre
    assert Rules(include_genres=frozenset({"science-fiction"})).anilist_variables() \
        == {"genreIn": ["Sci-Fi"]}


def _tmdb_params_sent(rules, monkeypatch, **overrides):
    cfg = Config(radarr_url="http://x", radarr_api_key="k", tmdb_api_key="key",
                 **overrides)
    source = TmdbSource(cfg)
    source.rules = rules
    calls = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [{"id": 1, "title": "Doc", "release_date": "2026-01-01",
                                 "genre_ids": [99], "vote_average": 8.0,
                                 "vote_count": 500}],
                    "total_pages": 1}

    monkeypatch.setattr(source.session, "get",
                        lambda url, params=None, timeout=None: calls.append(params) or Resp())
    items = source.fetch()
    return calls, items


def test_tmdb_source_searches_by_genre_and_network(monkeypatch):
    rules = {"movie": Rules(include_genres=frozenset({"documentary"})),
             "tv": Rules(include_networks=("netflix",))}
    calls, items = _tmdb_params_sent(rules, monkeypatch)
    assert calls[0]["with_genres"] == "99"                    # movies
    assert calls[1]["with_networks"] == "213"                 # TV
    assert items[0].genres == ("documentary",)


def test_trakt_source_searches_by_genre(monkeypatch):
    cfg = Config(radarr_url="http://x", radarr_api_key="k", trakt_client_id="id")
    source = TraktSource(cfg)
    source.rules = {"movie": Rules(include_genres=frozenset({"horror"}))}
    sent = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"show": {"title": "Show", "year": 2026, "rating": 9.0,
                              "votes": 900, "ids": {"tmdb": 5},
                              "genres": ["drama"], "network": "Netflix"}}]

    monkeypatch.setattr(source.session, "get",
                        lambda url, params=None, timeout=None: sent.append(params) or Resp())
    items = source.fetch()
    assert sent[0]["genres"] == "horror"                      # movies
    assert "genres" not in sent[1]                            # shows: no filter set
    show = [i for i in items if i.media_type == TV][0]
    assert show.genres == ("drama",) and show.network == "Netflix"


def test_anilist_source_searches_by_genre(monkeypatch):
    source = AniListSource(Config(radarr_url="http://x", radarr_api_key="k"))
    source.rules = {"anime": Rules(exclude_genres=frozenset({"ecchi"}))}
    sent = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"Page": {"media": [
                {"id": 1, "format": "TV", "averageScore": 90, "seasonYear": 2026,
                 "title": {"romaji": "A", "english": None}, "genres": ["Action"]}]}}}

    def fake_post(url, json=None, timeout=None):
        sent.update(json)
        return Resp()

    monkeypatch.setattr(source.session, "post", fake_post)
    items = source.fetch()
    assert sent["variables"]["genreNotIn"] == ["Ecchi"]
    assert "genre_not_in: $genreNotIn" in sent["query"]
    assert items[0].genres == ("Action",)


# ── Settings ─────────────────────────────────────────────────────────────────

@pytest.fixture
def settings(tmp_path):
    return SettingsStore(str(tmp_path / "settings.json"), SOURCE_DEFAULTS)


def test_filter_settings_round_trip(settings, tmp_path):
    assert settings.genre_filters["movie"] == {"include": [], "exclude": []}
    settings.update({"genre_filters": {"movie": {"include": ["documentary", "comedy"]}},
                     "network_filters": {"tv": {"exclude": ["netflix", "BBC Three"]}}})
    reloaded = SettingsStore(str(tmp_path / "settings.json"), SOURCE_DEFAULTS)
    assert reloaded.genre_filters["movie"]["include"] == ["comedy", "documentary"]
    assert reloaded.genre_filters["tv"] == {"include": [], "exclude": []}
    assert reloaded.network_filters["tv"]["exclude"] == ["BBC Three", "netflix"]

    rules = rules_for(reloaded, "tv")
    assert "excluded" in rules.network_reason("Netflix")


def test_moving_a_value_to_the_other_side(settings):
    settings.update({"genre_filters": {"tv": {"include": ["reality", "drama"]}}})
    settings.update({"genre_filters": {"tv": {"exclude": ["reality"]}}})
    assert settings.genre_filters["tv"] == {"include": ["drama"], "exclude": ["reality"]}


def test_bad_filter_settings_are_rejected(settings):
    with pytest.raises(SettingsError, match="Unknown genre"):
        settings.update({"genre_filters": {"movie": {"include": ["not-a-genre"]}}})
    with pytest.raises(SettingsError, match="both included and excluded"):
        settings.update({"genre_filters": {"movie": {"include": ["drama"],
                                                     "exclude": ["drama"]}}})
    with pytest.raises(SettingsError, match="kinds"):
        settings.update({"network_filters": {"movie": {"include": ["netflix"]}}})
    with pytest.raises(SettingsError, match="Unknown network"):
        settings.update({"network_filters": {"tv": {"include": ["<script>"]}}})
    with pytest.raises(SettingsError, match="at most"):
        settings.update({"network_filters": {"tv": {"include": [f"Net {i}" for i in range(51)]}}})


# ── Enforcement ──────────────────────────────────────────────────────────────

def test_sonarr_filters_on_its_own_genres_and_network():
    match = [{"title": "Big Show", "year": 2026, "tvdbId": 9, "images": [],
              "genres": ["Reality"], "network": "Netflix"}]
    item = MediaItem(title="Big Show", media_type=TV, source="metacritic", year=2026)

    sonarr, session = make_sonarr({"Big Show": match})
    assert sonarr.add(item, Rules(exclude_genres=frozenset({"reality"}))) \
        == state_mod.FILTERED
    assert sonarr.add(item, Rules(include_networks=("hbo",))) == state_mod.FILTERED
    assert session.posts == []
    assert sonarr.add(item, Rules(include_networks=("netflix",))) == state_mod.ADDED


def test_site_genres_count_when_the_arr_has_none():
    # Sonarr rarely reports anime genres like Ecchi; AniList does.
    match = [{"title": "Show", "year": 2026, "tvdbId": 9, "images": [],
              "genres": ["Anime", "Comedy"]}]
    item = MediaItem(title="Show", media_type=TV, source="anilist", year=2026,
                     anime=True, genres=("Ecchi", "Comedy"))
    sonarr, _ = make_sonarr({"Show": match})
    assert sonarr.add(item, Rules(exclude_genres=frozenset({"ecchi"}))) \
        == state_mod.FILTERED


def test_collect_drops_what_the_site_already_rules_out(monkeypatch, settings):
    class Src:
        def fetch(self):
            return [MediaItem(title="Doc", media_type=MOVIE, source="tmdb", year=2026,
                              genres=("documentary",)),
                    MediaItem(title="Thing", media_type=MOVIE, source="rt", year=2026),
                    MediaItem(title="Show", media_type=TV, source="trakt", year=2026,
                              network="Netflix")]

    monkeypatch.setattr("fresharr.runner.build_sources", lambda cfg, s: [Src()])
    settings.update({"genre_filters": {"movie": {"exclude": ["documentary"]}},
                     "network_filters": {"tv": {"exclude": ["netflix"]}}})
    config = Config(radarr_url="http://r", radarr_api_key="k",
                    sonarr_url="http://s", sonarr_api_key="k")
    titles = [i.title for i in collect_items(config, settings)]
    assert titles == ["Thing"]           # unknown genres pass, to be checked at add time


def test_filtered_titles_are_rechecked_when_filters_change(tmp_path):
    state = State(str(tmp_path / "state.json"))
    state.record("tv:show:2026", state_mod.FILTERED, "Show", "tv", "sig-a")
    assert state.should_skip("tv:show:2026", "sig-a")         # same filters: wait
    assert not state.should_skip("tv:show:2026", "sig-b")     # changed: look again
    state.record("tv:gone:2026", state_mod.NOT_FOUND, "Gone", "tv", "sig-a")
    assert state.should_skip("tv:gone:2026", "sig-b")         # only FILTERED re-checks
    state._items["tv:show:2026"]["at"] = time.time() - 30 * 86400
    assert not state.should_skip("tv:show:2026", "sig-a")     # and the old delay holds


def test_myanimelist_genres_include_themes_and_explicit_genres():
    from fresharr.sources.myanimelist import MyAnimeListSource
    source = MyAnimeListSource(Config(radarr_url="http://x", radarr_api_key="k"))
    item = source._parse_item({
        "mal_id": 1, "type": "TV", "title": "Show", "year": 2026, "score": 8.1,
        "genres": [{"mal_id": 1, "type": "anime", "name": "Action"}],
        "explicit_genres": [{"mal_id": 9, "type": "anime", "name": "Ecchi"}],
        "themes": [{"mal_id": 18, "type": "anime", "name": "Mecha"}]})
    assert item.genres == ("Action", "Ecchi", "Mecha")
    assert "excluded" in Rules(exclude_genres=frozenset({"ecchi"})).genre_reason(item.genres)
