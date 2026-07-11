import logging
import os
import sys

from . import __version__
from .config import Config
from .runner import run_once
from .scheduler import Scheduler
from .settings import SettingsStore
from .sources import SOURCE_DEFAULTS
from .web import create_app

log = logging.getLogger("fresharr")


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    config = Config.from_env()
    logging.getLogger().setLevel(config.log_level)
    settings = SettingsStore(config.settings_file, SOURCE_DEFAULTS)
    log.info("Fresharr %s starting (Radarr: %s, Sonarr: %s)",
             __version__,
             "on" if config.radarr_enabled else "off",
             "on" if config.sonarr_enabled else "off")

    if config.run_once:
        # For external schedulers: single pass, no web server.
        run_once(config, settings)
        return 0

    scheduler = Scheduler(config, settings)
    scheduler.start()

    app = create_app(config, settings, scheduler)
    log.info("Web interface listening on port %d", config.web_port)
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=config.web_port, threads=4)
    except KeyboardInterrupt:
        log.info("Interrupted; shutting down")
    finally:
        scheduler.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
