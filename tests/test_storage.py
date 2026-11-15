import json
import os
import subprocess
import sys
import tempfile

import pytest

from fresharr import storage
from fresharr.settings import SettingsStore
from fresharr.sources import SOURCE_DEFAULTS
from fresharr.state import State
import fresharr.state as state_mod


@pytest.fixture(autouse=True)
def clear_error():
    storage._set_error(None)
    yield
    storage._set_error(None)


def test_save_keeps_previous_version_as_backup(tmp_path):
    path = str(tmp_path / "settings.json")
    storage.save_json(path, {"v": 1})
    storage.save_json(path, {"v": 2})
    assert json.loads(open(path).read()) == {"v": 2}
    assert json.loads(open(path + ".bak").read()) == {"v": 1}
    assert not [f for f in os.listdir(tmp_path) if f.startswith(".tmp-")]


def test_unreadable_file_falls_back_to_backup_and_is_kept_aside(tmp_path):
    path = str(tmp_path / "settings.json")
    storage.save_json(path, {"v": 1})
    storage.save_json(path, {"v": 2})
    open(path, "w").close()                       # what a hard reboot can leave
    assert storage.load_json(path, "settings") == {"v": 1}
    assert os.path.exists(path + ".corrupt")      # not destroyed by the next save


def test_missing_file_after_interrupted_save_uses_backup(tmp_path):
    path = str(tmp_path / "settings.json")
    storage.save_json(path, {"v": 1})
    os.replace(path, path + ".bak")               # stopped between the two renames
    assert storage.load_json(path, "settings") == {"v": 1}


def test_fresh_install_and_both_bad(tmp_path):
    path = str(tmp_path / "settings.json")
    assert storage.load_json(path, "settings") is None
    open(path, "w").write("{")
    open(path + ".bak", "w").write("{")
    assert storage.load_json(path, "settings") is None


def test_settings_survive_an_emptied_file(tmp_path):
    path = str(tmp_path / "settings.json")
    settings = SettingsStore(path, SOURCE_DEFAULTS)
    settings.update({"run_interval_days": 7})
    settings.update({"movie_languages": ["en"]})
    open(path, "w").close()
    reloaded = SettingsStore(path, SOURCE_DEFAULTS)
    assert reloaded.run_interval_days == 7.0      # from the backup, one change back
    reloaded.update({"run_interval_days": 3})
    assert SettingsStore(path, SOURCE_DEFAULTS).run_interval_days == 3.0


def test_failed_save_is_not_applied(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    settings = SettingsStore(path, SOURCE_DEFAULTS)

    def denied(*args, **kwargs):
        raise PermissionError(13, "Permission denied", str(tmp_path))

    monkeypatch.setattr(storage.tempfile, "mkstemp", denied)
    with pytest.raises(OSError):
        settings.update({"run_interval_days": 7})
    assert settings.run_interval_days == 1.0      # doesn't pretend it worked
    assert "permission denied" in storage.storage_error()

    monkeypatch.undo()
    settings.update({"run_interval_days": 7})
    assert settings.run_interval_days == 7.0
    assert storage.storage_error() is None        # cleared once saving works


def test_web_reports_a_failed_save(tmp_path, monkeypatch):
    from test_web import FakeScheduler
    from fresharr.config import Config
    from fresharr.web import create_app
    config = Config(radarr_url="http://x", radarr_api_key="k",
                    state_file=str(tmp_path / "state.json"),
                    settings_file=str(tmp_path / "settings.json"),
                    status_file=str(tmp_path / "status.json"))
    settings = SettingsStore(config.settings_file, SOURCE_DEFAULTS)
    client = create_app(config, settings, FakeScheduler()).test_client()

    def denied(*args, **kwargs):
        raise PermissionError(13, "Permission denied", str(tmp_path))

    monkeypatch.setattr(storage.tempfile, "mkstemp", denied)
    resp = client.post("/api/settings", json={"run_interval_days": 7})
    assert resp.status_code == 500
    assert "not being saved" in resp.get_json()["error"]
    overview = client.get("/api/overview").get_json()
    assert "permission denied" in overview["storage_error"]
    assert overview["settings"]["run_interval_days"] == 1.0


def test_state_round_trip_and_backup(tmp_path):
    path = str(tmp_path / "state.json")
    state = State(path)
    state.record("movie:a:2026", state_mod.ADDED, "A")
    state.save()
    state.record("movie:b:2026", state_mod.ADDED, "B")
    state.save()
    open(path, "w").write("{not json")
    assert State(path).should_skip("movie:a:2026")   # restored from the backup


def test_check_writable(tmp_path):
    assert storage.check_writable(str(tmp_path)) is None
    assert not os.path.exists(tmp_path / ".write-test")


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0,
                    reason="needs root to change ownership")
def test_drop_privileges_fixes_ownership_then_runs_as_puid():
    import pathlib
    import shutil
    # Not pytest's tmp_path: that sits under a root-only folder PUID 99
    # couldn't even reach, which no real /config does.
    base = pathlib.Path(tempfile.mkdtemp(dir="/tmp"))
    os.chmod(base, 0o755)
    config_dir = base / "config"
    config_dir.mkdir()                              # owned by root, like a
    (config_dir / "settings.json").write_text("{}")  # Docker-made appdata dir
    try:
        _run_drop_privileges(config_dir)
    finally:
        shutil.rmtree(base)


def _run_drop_privileges(config_dir):
    script = (
        "import os, sys; from fresharr.privileges import drop_privileges; "
        "from fresharr.storage import check_writable; "
        f"drop_privileges([{str(config_dir)!r}]); "
        "print(os.getuid(), os.getgid(), os.getgroups()); "
        f"print(check_writable({str(config_dir)!r}))")
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, env={**os.environ, "PUID": "99", "PGID": "100"},
                         check=True).stdout.splitlines()
    assert out[0] == "99 100 []"
    assert out[1] == "None"                         # it can write there now
    st = os.stat(config_dir / "settings.json")
    assert (st.st_uid, st.st_gid) == (99, 100)


def test_drop_privileges_does_nothing_when_not_root(monkeypatch, tmp_path):
    from fresharr import privileges
    monkeypatch.setattr(privileges.os, "geteuid", lambda: 1000)
    called = []
    monkeypatch.setattr(privileges.os, "setuid", lambda uid: called.append(uid))
    privileges.drop_privileges([str(tmp_path)])
    assert called == []
