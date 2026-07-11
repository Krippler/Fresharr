import logging
import threading
import time

from .config import Config
from .runner import run_once
from .settings import SettingsStore
from .status import load_status

log = logging.getLogger(__name__)

_TICK_SECONDS = 30


class Scheduler(threading.Thread):
    """Runs discovery on the interval configured in the web UI.

    The interval is re-read from the settings store on every tick, so
    changing it in the UI takes effect immediately - no restart. The last
    run time is persisted in status.json, so a container restart doesn't
    trigger an early run.
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
        last = load_status(self.config.status_file).get("last_run_at")
        if not isinstance(last, (int, float)):
            return time.time()  # never ran: due immediately
        return last + self.settings.run_interval_days * 86400

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
            self._wake.wait(timeout=_TICK_SECONDS)
            self._wake.clear()
