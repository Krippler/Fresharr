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
    assert b"Discovery sites" in resp.data


def test_overview_lists_all_sources(env):
    client, _, _ = env
    data = client.get("/api/overview").get_json()
    names = {s["name"] for s in data["sources"]}
    assert names == {"rottentomatoes", "imdb", "tmdb", "trakt"}
    rt = next(s for s in data["sources"] if s["name"] == "rottentomatoes")
    assert rt["enabled"] and rt["configured"]
    tmdb = next(s for s in data["sources"] if s["name"] == "tmdb")
    assert not tmdb["configured"] and tmdb["requires"] == "TMDB_API_KEY"
    assert data["settings"]["run_interval_days"] == 1.0


def test_toggle_source(env):
    client, settings, _ = env
    resp = client.post("/api/settings",
                       json={"sources": {"imdb": {"enabled": True}}})
    assert resp.status_code == 200
    assert settings.is_enabled("imdb")


def test_interval_update_and_clamp(env):
    client, settings, _ = env
    assert client.post("/api/settings",
                       json={"run_interval_days": 7}).status_code == 200
    assert settings.run_interval_days == 7.0
    data = client.post("/api/settings",
                       json={"run_interval_days": 0.1}).get_json()
    assert data["run_interval_days"] == 1.0  # clamped, not errored


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
