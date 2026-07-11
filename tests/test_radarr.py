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
    cfg = Config(sources=["rottentomatoes"],
                 radarr_url="http://radarr:7878", radarr_api_key="k")
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
