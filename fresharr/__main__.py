import logging
import sys
import time

from . import __version__
from .config import Config
from .runner import run_once

log = logging.getLogger("fresharr")


def main() -> int:
    logging.basicConfig(
        level=os_log_level(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    config = Config.from_env()
    logging.getLogger().setLevel(config.log_level)
    log.info("Fresharr %s starting (Radarr: %s, Sonarr: %s)",
             __version__,
             "on" if config.radarr_enabled else "off",
             "on" if config.sonarr_enabled else "off")

    while True:
        try:
            run_once(config)
        except Exception:
            log.exception("Run failed unexpectedly")
        if config.run_once:
            return 0
        log.info("Sleeping %.1f day(s) until next run", config.run_interval_days)
        try:
            time.sleep(config.run_interval_days * 86400)
        except KeyboardInterrupt:
            log.info("Interrupted; shutting down")
            return 0


def os_log_level() -> str:
    import os
    return os.environ.get("LOG_LEVEL", "INFO").upper()


if __name__ == "__main__":
    sys.exit(main())
