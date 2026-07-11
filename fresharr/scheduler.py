import logging
import random
import threading
import time

from .config import Config
from .runner import run_once
from .settings import SettingsStore
from .status import load_status, save_status

log = logging.getLogger(__name__)

_TICK_SECONDS = 30

# The interval chosen in the web UI is a target cadence, not an exact
# timer: each next run lands at a random moment within +/- JITTER of the
# target, floored at MIN_GAP after the previous run. With the daily
# preset that means somewhere between 18 and 30 hours later - a different
# time of day on every cycle, so the discovery sites never see Fresharr
# at one predictable hour.
MIN_GAP_SECONDS = 18 * 3600
JITTER_SECONDS = 6 * 3600


def pick_next_run(after: float, interval_days: float) -> float:
    target = interval_days * 86400 + random.uniform(-JITTER_SECONDS, JITTER_SECONDS)
    return after + max(MIN_GAP_SECONDS, target)


class Scheduler(threading.Thread):
    """Runs discovery around the user's chosen cadence, at randomized times
    (always >= 18h between runs).

    The next run time is persisted in status.json, so a container restart
    neither reruns early nor rerolls the schedule. A missing next run time
    (first ever start) means run immediately.
    """

    def __init__(self, config: Config, settings: SettingsStore):
        super().__init__(name="scheduler", daemon=True)
        self.config = config
        self.settings = settings
        self.running = False  # True while a discovery run is in progress
        self._wake = threading.Event()
        self._run_requested = False
        self._stop = False

    def request_run(self) -> None:
        """Run now (web UI button), regardless of schedule."""
        self._run_requested = True
        self._wake.set()

    def stop(self) -> None:
        self._stop = True
        self._wake.set()

    def next_run_at(self) -> float:
        next_at = load_status(self.config.status_file).get("next_run_at")
        if isinstance(next_at, (int, float)):
            return float(next_at)
        return 0.0  # never scheduled: due immediately

    def _schedule_next(self) -> None:
        next_at = pick_next_run(time.time(), self.settings.run_interval_days)
        try:
            status = load_status(self.config.status_file)
            status["next_run_at"] = int(next_at)
            save_status(self.config.status_file, status)
        except OSError as exc:
            log.warning("Could not persist next run time: %s", exc)
        log.info("Next automatic run: %s",
                 time.strftime("%Y-%m-%d %H:%M", time.localtime(next_at)))

    def run(self) -> None:
        while not self._stop:
            if self._run_requested or time.time() >= self.next_run_at():
                self._run_requested = False
                self.running = True
                try:
                    run_once(self.config, self.settings)
                except Exception:
                    log.exception("Discovery run failed unexpectedly")
                finally:
                    self.running = False
                    self._schedule_next()
            self._wake.wait(timeout=_TICK_SECONDS)
            self._wake.clear()
