"""Last-run status persisted for the web UI and for scheduling across
container restarts."""

import json
import logging
import os
import tempfile

log = logging.getLogger(__name__)


def load_status(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read status file %s (%s)", path, exc)
        return {}


def save_status(path: str, data: dict) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".status-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
