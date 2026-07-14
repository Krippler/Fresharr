import pytest

from fresharr.config import Config
from fresharr.settings import SettingsStore
from fresharr.sources import SOURCE_DEFAULTS
from fresharr.web import create_app


class FakeScheduler:
    def __init__(self):
        self.running = False
        self.run_requests = 0

    def request_run(self):
        self.run_requests += 1

    def next_run_at(self):
        return 2_000_000_000


@pytest.fixture
def env(tmp_path):
    config = Config(radarr_url="http://x", radarr_api_key="k",
                    state_file=str(tmp_path / "state.json"),
                    settings_file=str(tmp_path / "settings.json"),
                    status_file=str(tmp_path / "status.json"))
    settings = SettingsStore(config.settings_file, SOURCE_DEFAULTS)
    scheduler = FakeScheduler()
    app = create_app(config, settings, scheduler)
    app.config["TESTING"] = True
    return app.test_client(), settings, scheduler


def test_index_serves_ui(env):
    client, _, _ = env
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Fresharr" in resp.data
    assert b"Discovery &mdash; Movies" in resp.data


def test_overview_lists_all_sources(env):
    client, _, _ = env
    data = client.get("/api/overview").get_json()
    names = {s["name"] for s in data["sources"]}
    assert names == {"rottentomatoes", "metacritic", "letterboxd",
                     "tmdb", "trakt", "anilist", "myanimelist"}
    rt = next(s for s in data["sources"] if s["name"] == "rottentomatoes")
    assert rt["enabled"] and rt["configured"]
    tmdb = next(s for s in data["sources"] if s["name"] == "tmdb")
    assert not tmdb["configured"] and tmdb["requires"] == "TMDB_API_KEY"
    anilist = next(s for s in data["sources"] if s["name"] == "anilist")
    assert anilist["category"] == "Anime"
    assert anilist["configured"] and not anilist["enabled"]
    assert data["settings"]["run_interval_days"] == 1.0


def test_toggle_source(env):
    client, settings, _ = env
    resp = client.post("/api/settings",
                       json={"sources": {"metacritic": {"enabled": True}}})
    assert resp.status_code == 200
    assert settings.is_enabled("metacritic")


def test_interval_update_and_clamp(env):
    client, settings, _ = env
    assert client.post("/api/settings",
                       json={"run_interval_days": 7}).status_code == 200
    assert settings.run_interval_days == 7.0
    data = client.post("/api/settings",
                       json={"run_interval_days": 0.1}).get_json()
    assert data["run_interval_days"] == 1.0  # clamped, not errored


def test_language_settings(env):
    client, settings, _ = env
    overview = client.get("/api/overview").get_json()
    assert {"code": "en", "label": "English"} in overview["language_options"]
    assert overview["settings"]["movie_languages"] == []
    assert overview["settings"]["tv_languages"] == []
    assert overview["settings"]["anime_languages"] == []

    resp = client.post("/api/settings",
                       json={"movie_languages": ["en", "fr"],
                             "tv_languages": ["ko"],
                             "anime_languages": ["ja"]})
    assert resp.status_code == 200
    assert settings.movie_languages == ["en", "fr"]
    assert settings.tv_languages == ["ko"]
    assert settings.anime_languages == ["ja"]

    resp = client.post("/api/settings", json={"movie_languages": ["not-a-code"]})
    assert resp.status_code == 400


def test_unknown_source_is_400(env):
    client, _, _ = env
    resp = client.post("/api/settings",
                       json={"sources": {"netflix": {"enabled": True}}})
    assert resp.status_code == 400
    assert "Unknown source" in resp.get_json()["error"]


def test_run_now(env):
    client, _, scheduler = env
    assert client.post("/api/run").status_code == 200
    assert scheduler.run_requests == 1
    scheduler.running = True
    assert client.post("/api/run").status_code == 409


def test_health(env):
    client, _, _ = env
    assert client.get("/health").get_json()["status"] == "ok"


def test_options_editable_via_api(env):
    client, settings, _ = env
    overview = client.get("/api/overview").get_json()
    radarr_keys = {opt["key"] for opt in overview["connections"]["radarr"]}
    assert {"radarr_url", "radarr_api_key",
            "radarr_quality_profile", "radarr_root_folder"} <= radarr_keys
    general_keys = {opt["key"] for opt in overview["general_options"]}
    assert {"max_items_per_run", "min_year"} <= general_keys
    rt = next(s for s in overview["sources"] if s["name"] == "rottentomatoes")
    assert {"rt_min_critics_score", "rt_min_audience_score"} <= \
        {opt["key"] for opt in rt["options"]}

    resp = client.post("/api/settings",
                       json={"options": {"rt_min_critics_score": 90}})
    assert resp.status_code == 200
    assert settings.options()["rt_min_critics_score"] == 90
    overview = client.get("/api/overview").get_json()
    rt = next(s for s in overview["sources"] if s["name"] == "rottentomatoes")
    value = next(o["value"] for o in rt["options"]
                 if o["key"] == "rt_min_critics_score")
    assert value == 90

    resp = client.post("/api/settings",
                       json={"options": {"rt_min_critics_score": 500}})
    assert resp.status_code == 400


def test_arr_choices_endpoint(env, monkeypatch):
    client, _, _ = env

    # Unknown app 404s; unconfigured app reports configured/connected false
    assert client.get("/api/arr/plex/choices").status_code == 404
    data = client.get("/api/arr/sonarr/choices").get_json()
    assert data == {"configured": False, "connected": False,
                    "profiles": [], "root_folders": []}

    # Configured app returns live profiles and root folders
    class FakeRadarr:
        def __init__(self, cfg):
            pass

        def _get(self, path, **params):
            if path == "qualityprofile":
                return [{"id": 1, "name": "HD-1080p"}, {"id": 2, "name": "4K"}]
            if path == "rootfolder":
                return [{"path": "/movies"}, {"path": "/movies4k"}]
            raise AssertionError(path)

    monkeypatch.setattr("fresharr.web.Radarr", FakeRadarr)
    data = client.get("/api/arr/radarr/choices").get_json()
    assert data["configured"] is True
    assert data["connected"] is True
    assert [p["name"] for p in data["profiles"]] == ["HD-1080p", "4K"]
    assert data["root_folders"] == ["/movies", "/movies4k"]

    # Unreachable app degrades to connected:false with a concise reason
    import requests

    class BrokenRadarr:
        def __init__(self, cfg):
            pass

        def _get(self, path, **params):
            raise requests.ConnectionError("Connection refused")

    monkeypatch.setattr("fresharr.web.Radarr", BrokenRadarr)
    data = client.get("/api/arr/radarr/choices").get_json()
    assert data["configured"] is True
    assert data["connected"] is False
    assert "check URL/port" in data["error"]
    assert data["profiles"] == []


def test_tmdb_key_via_ui_marks_source_configured(env):
    client, _, _ = env
    overview = client.get("/api/overview").get_json()
    tmdb = next(s for s in overview["sources"] if s["name"] == "tmdb")
    assert not tmdb["configured"]

    client.post("/api/settings", json={"options": {"tmdb_api_key": "abc123"}})
    overview = client.get("/api/overview").get_json()
    tmdb = next(s for s in overview["sources"] if s["name"] == "tmdb")
    assert tmdb["configured"]
