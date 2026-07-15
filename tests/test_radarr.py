import json

import pytest
import requests

from fresharr import state
from fresharr.arr.radarr import Radarr
from fresharr.config import Config
from fresharr.models import MOVIE, MediaItem


class FakeSession:
    """Stands in for requests.Session, replaying canned Radarr API responses."""

    def __init__(self, routes):
        self.routes = routes  # (method, path-suffix) -> payload or callable
        self.headers = {}
        self.posts: list[tuple[str, dict]] = []

    def _respond(self, method, url, payload=None):
        for (m, suffix), response in self.routes.items():
            if m == method and url.split("?")[0].endswith(suffix):
                if callable(response):
                    return response(payload)
                return FakeResponse(response)
        raise AssertionError(f"Unexpected {method} {url}")

    def get(self, url, params=None, timeout=None):
        return self._respond("GET", url)

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return self._respond("POST", url, json)


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


LOOKUP_RESULT = [{"title": "Dune: Part Two", "year": 2024, "tmdbId": 693134,
                  "titleSlug": "dune-part-two", "images": []}]


def make_radarr(routes) -> tuple[Radarr, FakeSession]:
    cfg = Config(radarr_url="http://radarr:7878", radarr_api_key="k")
    radarr = Radarr(cfg)
    session = FakeSession(routes)
    radarr.session = session
    return radarr, session


ITEM = MediaItem(title="Dune: Part Two", media_type=MOVIE,
                 source="rottentomatoes", year=2024)


def test_add_posts_expected_payload():
    radarr, session = make_radarr({
        ("GET", "/movie"): [],
        ("GET", "/movie/lookup"): LOOKUP_RESULT,
        ("GET", "/qualityprofile"): [{"id": 4, "name": "HD-1080p"}],
        ("GET", "/rootfolder"): [{"path": "/movies"}],
        ("POST", "/movie"): {"title": "Dune: Part Two", "year": 2024, "tmdbId": 693134},
    })
    assert radarr.add(ITEM) == state.ADDED
    (_, payload), = session.posts
    assert payload["tmdbId"] == 693134
    assert payload["qualityProfileId"] == 4
    assert payload["rootFolderPath"] == "/movies"
    assert payload["monitored"] is True
    assert payload["minimumAvailability"] == "released"
    assert payload["addOptions"] == {"searchForMovie": True}


def test_add_creates_and_applies_tag():
    radarr, session = make_radarr({
        ("GET", "/movie"): [],
        ("GET", "/movie/lookup"): LOOKUP_RESULT,
        ("GET", "/qualityprofile"): [{"id": 4, "name": "HD-1080p"}],
        ("GET", "/rootfolder"): [{"path": "/movies"}],
        ("GET", "/tag"): [{"id": 1, "label": "other"}],
        ("POST", "/tag"): lambda payload: FakeResponse({"id": 7, "label": payload["label"]}),
        ("POST", "/movie"): {"title": "Dune: Part Two", "year": 2024, "tmdbId": 693134},
    })
    radarr.tag = "fresharr"          # not in the library's tag list -> created
    assert radarr.add(ITEM) == state.ADDED
    assert ("http://radarr:7878/api/v3/tag", {"label": "fresharr"}) in session.posts
    movie_payload = next(p for (u, p) in session.posts if u.endswith("/movie"))
    assert movie_payload["tags"] == [7]


def test_add_reuses_existing_tag_case_insensitively():
    radarr, session = make_radarr({
        ("GET", "/movie"): [],
        ("GET", "/movie/lookup"): LOOKUP_RESULT,
        ("GET", "/qualityprofile"): [{"id": 4, "name": "HD-1080p"}],
        ("GET", "/rootfolder"): [{"path": "/movies"}],
        ("GET", "/tag"): [{"id": 3, "label": "Fresharr"}],
        ("POST", "/movie"): {"title": "Dune: Part Two", "year": 2024, "tmdbId": 693134},
    })
    radarr.tag = "fresharr"
    assert radarr.add(ITEM) == state.ADDED
    assert all(not u.endswith("/tag") for (u, _) in session.posts)  # no tag created
    movie_payload = next(p for (u, p) in session.posts if u.endswith("/movie"))
    assert movie_payload["tags"] == [3]


def test_add_without_tag_sends_no_tags_key():
    radarr, session = make_radarr({
        ("GET", "/movie"): [],
        ("GET", "/movie/lookup"): LOOKUP_RESULT,
        ("GET", "/qualityprofile"): [{"id": 4, "name": "HD-1080p"}],
        ("GET", "/rootfolder"): [{"path": "/movies"}],
        ("POST", "/movie"): {"title": "Dune: Part Two", "year": 2024, "tmdbId": 693134},
    })
    assert radarr.add(ITEM) == state.ADDED
    (_, payload), = session.posts
    assert "tags" not in payload   # no /tag call, unchanged payload


ITALIAN_LOOKUP = [{"title": "Dune: Part Two", "year": 2024, "tmdbId": 693134,
                   "titleSlug": "dune-part-two", "images": [],
                   "originalLanguage": {"id": 5, "name": "Italian"}}]


def test_add_skips_when_language_not_allowed():
    radarr, session = make_radarr({
        ("GET", "/movie"): [],
        ("GET", "/movie/lookup"): ITALIAN_LOOKUP,
    })
    # Filter allows only English/Japanese; the match is Italian -> filtered out.
    assert radarr.add(ITEM, ["en", "ja"]) == state.FILTERED
    assert session.posts == []            # never attempted the add


def test_add_allows_matching_language():
    radarr, session = make_radarr({
        ("GET", "/movie"): [],
        ("GET", "/movie/lookup"): ITALIAN_LOOKUP,
        ("GET", "/qualityprofile"): [{"id": 4, "name": "HD-1080p"}],
        ("GET", "/rootfolder"): [{"path": "/movies"}],
        ("POST", "/movie"): {"title": "Dune: Part Two", "year": 2024, "tmdbId": 693134},
    })
    assert radarr.add(ITEM, ["it", "en"]) == state.ADDED  # Italian is allowed


def test_add_passes_unknown_language():
    # An empty/unknown originalLanguage never gets dropped by the filter.
    radarr, _ = make_radarr({
        ("GET", "/movie"): [],
        ("GET", "/movie/lookup"): LOOKUP_RESULT,  # no originalLanguage field
        ("GET", "/qualityprofile"): [{"id": 4, "name": "HD-1080p"}],
        ("GET", "/rootfolder"): [{"path": "/movies"}],
        ("POST", "/movie"): {"title": "Dune: Part Two", "year": 2024, "tmdbId": 693134},
    })
    assert radarr.add(ITEM, ["ja"]) == state.ADDED


def test_add_skips_when_already_in_library():
    radarr, session = make_radarr({
        ("GET", "/movie"): [{"title": "Dune: Part Two", "year": 2024, "tmdbId": 693134}],
    })
    assert radarr.add(ITEM) == state.EXISTS
    assert session.posts == []


def test_add_reports_not_found():
    radarr, _ = make_radarr({
        ("GET", "/movie"): [],
        ("GET", "/movie/lookup"): [{"title": "Something Else", "year": 2001}],
    })
    assert radarr.add(ITEM) == state.NOT_FOUND


def test_add_treats_duplicate_validation_as_exists():
    radarr, _ = make_radarr({
        ("GET", "/movie"): [],
        ("GET", "/movie/lookup"): LOOKUP_RESULT,
        ("GET", "/qualityprofile"): [{"id": 4, "name": "HD-1080p"}],
        ("GET", "/rootfolder"): [{"path": "/movies"}],
        ("POST", "/movie"): lambda payload: FakeResponse(
            [{"errorMessage": "This movie has already been added"}], status=400),
    })
    assert radarr.add(ITEM) == state.EXISTS


def test_missing_quality_profile_raises_helpful_error():
    from fresharr.arr.base import ArrError
    radarr, _ = make_radarr({
        ("GET", "/movie"): [],
        ("GET", "/movie/lookup"): LOOKUP_RESULT,
        ("GET", "/qualityprofile"): [{"id": 4, "name": "HD-1080p"}],
    })
    radarr.quality_profile = "Ultra-HD"
    with pytest.raises(ArrError, match="Ultra-HD"):
        radarr.add(ITEM)
