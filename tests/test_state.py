import json
import time

from fresharr import state as state_mod
from fresharr.state import State


def test_roundtrip(tmp_path):
    path = str(tmp_path / "state.json")
    state = State(path)
    state.record("movie:dune:2021", state_mod.ADDED, "Dune")
    state.save()

    reloaded = State(path)
    assert reloaded.should_skip("movie:dune:2021")
    assert not reloaded.should_skip("movie:other:2021")


def test_not_found_retried_after_delay(tmp_path):
    path = str(tmp_path / "state.json")
    state = State(path, retry_not_found_days=7)
    state.record("movie:new:2026", state_mod.NOT_FOUND, "New")
    assert state.should_skip("movie:new:2026")

    # Simulate the entry being 8 days old
    state._items["movie:new:2026"]["at"] = int(time.time()) - 8 * 86400
    assert not state.should_skip("movie:new:2026")


def test_failed_always_retried(tmp_path):
    state = State(str(tmp_path / "state.json"))
    state.record("movie:flaky:2026", state_mod.FAILED, "Flaky")
    assert not state.should_skip("movie:flaky:2026")


def test_corrupt_file_starts_fresh(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    state = State(str(path))
    assert len(state) == 0


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "state.json"
    state = State(str(path))
    state.record("k", state_mod.ADDED, "T")
    state.save()
    assert json.loads(path.read_text())["items"]["k"]["status"] == state_mod.ADDED
