import json

import requests

from fresharr import state
from fresharr.arr.sonarr import Sonarr
from fresharr.config import Config
from fresharr.models import TV, MediaItem


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code}")
            error.response = self
            raise error

    def json(self):
        return self._payload


class FakeSession:
    """Replays canned Sonarr API responses; lookups are keyed by term."""

    def __init__(self, lookups, series_library=None):
        self.lookups = lookups
        self.series_library = series_library or []
        self.headers = {}
        self.posts = []
        self.lookup_terms = []

    def get(self, url, params=None, timeout=None):
        path = url.split("?")[0]
        if path.endswith("/series/lookup"):
            term = (params or {}).get("term", "")
            self.lookup_terms.append(term)
            return FakeResponse(self.lookups.get(term, []))
        if path.endswith("/series"):
            return FakeResponse(self.series_library)
        if path.endswith("/qualityprofile"):
            return FakeResponse([{"id": 2, "name": "HD-1080p"}])
        if path.endswith("/rootfolder"):
            return FakeResponse([{"path": "/tv"}, {"path": "/tv/Anime"}])
        if path.endswith("/languageprofile"):
            return FakeResponse([], status=404)
        raise AssertionError(f"Unexpected GET {url}")

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return FakeResponse(dict(json or {}, id=1))


def make_sonarr(lookups, **overrides) -> tuple[Sonarr, FakeSession]:
    cfg = Config(sonarr_url="http://sonarr:8989", sonarr_api_key="k",
                 radarr_url="", radarr_api_key="")
    for key, value in overrides.items():
        setattr(cfg, key, value)
    sonarr = Sonarr(cfg)
    session = FakeSession(lookups)
    sonarr.session = session
    return sonarr, session


FRIEREN_MATCH = [{"title": "Sousou no Frieren", "year": 2026, "tvdbId": 424536,
                  "titleSlug": "frieren", "images": []}]


def test_anime_added_with_anime_series_type():
    item = MediaItem(title="Frieren: Beyond Journey's End", media_type=TV,
                     source="anilist", year=2026,
                     alt_titles=("Sousou no Frieren",), anime=True)
    # English title finds nothing; the romaji alternate title matches.
    sonarr, session = make_sonarr({
        "Frieren: Beyond Journey's End": [],
        "Sousou no Frieren": FRIEREN_MATCH,
    })
    assert sonarr.add(item) == state.ADDED
    assert session.lookup_terms == ["Frieren: Beyond Journey's End",
                                    "Sousou no Frieren"]
    (_, payload), = session.posts
    assert payload["seriesType"] == "anime"
    assert payload["tvdbId"] == 424536
    assert payload["seasonFolder"] is True


def test_anime_uses_dedicated_root_folder():
    item = MediaItem(title="Sousou no Frieren", media_type=TV, source="anilist",
                     year=2026, anime=True)
    sonarr, session = make_sonarr({"Sousou no Frieren": FRIEREN_MATCH},
                                  sonarr_anime_root_folder="/tv/Anime")
    assert sonarr.add(item) == state.ADDED
    (_, payload), = session.posts
    assert payload["rootFolderPath"] == "/tv/Anime"


def test_non_anime_uses_main_root_folder_even_with_anime_folder_set():
    item = MediaItem(title="Sousou no Frieren", media_type=TV,
                     source="rottentomatoes", year=2026)  # not anime
    sonarr, session = make_sonarr({"Sousou no Frieren": FRIEREN_MATCH},
                                  sonarr_anime_root_folder="/tv/Anime")
    assert sonarr.add(item) == state.ADDED
    (_, payload), = session.posts
    assert payload["rootFolderPath"] == "/tv"   # main folder, not anime


def test_anime_falls_back_to_main_folder_when_unset():
    item = MediaItem(title="Sousou no Frieren", media_type=TV, source="anilist",
                     year=2026, anime=True)
    sonarr, session = make_sonarr({"Sousou no Frieren": FRIEREN_MATCH})  # no anime folder
    assert sonarr.add(item) == state.ADDED
    (_, payload), = session.posts
    assert payload["rootFolderPath"] == "/tv"


def test_regular_show_uses_standard_series_type():
    item = MediaItem(title="Sousou no Frieren", media_type=TV,
                     source="rottentomatoes", year=2026)
    sonarr, session = make_sonarr({"Sousou no Frieren": FRIEREN_MATCH})
    assert sonarr.add(item) == state.ADDED
    (_, payload), = session.posts
    assert payload["seriesType"] == "standard"


def test_series_added_without_auto_search_by_default():
    item = MediaItem(title="Sousou no Frieren", media_type=TV,
                     source="rottentomatoes", year=2026)
    sonarr, session = make_sonarr({"Sousou no Frieren": FRIEREN_MATCH})
    sonarr.add(item)
    (_, payload), = session.posts
    assert payload["addOptions"]["searchForMissingEpisodes"] is False


def test_series_already_in_library_via_lookup_id():
    item = MediaItem(title="Sousou no Frieren", media_type=TV,
                     source="rottentomatoes", year=2026)
    # The lookup result carries a non-zero library id -> already added.
    sonarr, session = make_sonarr({"Sousou no Frieren": [
        {"title": "Sousou no Frieren", "year": 2026, "tvdbId": 424536, "id": 7}]})
    assert sonarr.add(item) == state.EXISTS
    assert session.posts == []


def test_no_match_reports_not_found():
    item = MediaItem(title="Unknown Show", media_type=TV, source="s", year=2026)
    sonarr, _ = make_sonarr({"Unknown Show": []})
    assert sonarr.add(item) == state.NOT_FOUND
