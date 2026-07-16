import time

from fresharr.config import Config
from fresharr.scheduler import (
    JITTER_SECONDS,
    MIN_GAP_SECONDS,
    Scheduler,
    pick_next_run,
)
from fresharr.settings import SettingsStore
from fresharr.sources import SOURCE_DEFAULTS
from fresharr.status import save_status

DAY = 86400
HOUR = 3600


def test_daily_interval_lands_between_18_and_30_hours():
    gaps = {pick_next_run(0, 1.0) for _ in range(300)}
    assert all(MIN_GAP_SECONDS <= g <= DAY + JITTER_SECONDS for g in gaps)
    assert min(gaps) < 22 * HOUR   # jitter actually reaches below the day mark
    assert max(gaps) > 26 * HOUR   # ... and above it
    assert len(gaps) > 250         # times are genuinely random, not quantized


def test_weekly_interval_jitters_around_seven_days():
    gaps = [pick_next_run(0, 7.0) for _ in range(300)]
    assert all(7 * DAY - JITTER_SECONDS <= g <= 7 * DAY + JITTER_SECONDS
               for g in gaps)


def test_minimum_gap_enforced():
    # Even an (impossible) tiny interval never schedules within 18 hours
    gaps = [pick_next_run(0, 0.1) for _ in range(50)]
    assert all(g >= MIN_GAP_SECONDS for g in gaps)


def test_offset_from_given_time():
    assert pick_next_run(1_000_000, 1.0) >= 1_000_000 + MIN_GAP_SECONDS


def test_reschedule_recomputes_next_run_from_last_run(tmp_path):
    status_file = str(tmp_path / "status.json")
    settings_file = str(tmp_path / "settings.json")
    config = Config(status_file=status_file, settings_file=settings_file)
    settings = SettingsStore(settings_file, SOURCE_DEFAULTS)
    last = int(time.time()) - HOUR
    save_status(status_file, {"last_run_at": last, "next_run_at": last + DAY})

    scheduler = Scheduler(config, settings)
    settings.update({"run_interval_days": 7})
    scheduler.reschedule()

    next_at = scheduler.next_run_at()
    # Weekly cadence measured from the last run, within jitter.
    assert last + 7 * DAY - JITTER_SECONDS <= next_at <= last + 7 * DAY + JITTER_SECONDS
