"""Durable JSON files in /config.

Every file Fresharr keeps (settings, state, status) goes through here, so
they all get the same guarantees:

- Writes are flushed to disk before they replace the old file, so a hard
  reboot can't leave an empty or half-written file behind.
- The previous version is kept as <name>.bak. If the main file is missing or
  unreadable at startup, the backup is used, and the unreadable file is kept
  aside as <name>.corrupt rather than overwritten.
- A failed write is remembered, so the web interface can say that settings
  aren't being saved instead of looking as if they were.
"""

import json
import logging
import os
import tempfile
import threading

log = logging.getLogger(__name__)

_error_lock = threading.Lock()
_last_error: str | None = None


def storage_error() -> str | None:
    """Why the most recent write failed, or None if it succeeded."""
    with _error_lock:
        return _last_error


def _set_error(message: str | None) -> None:
    global _last_error
    with _error_lock:
        _last_error = message


def _describe(exc: OSError, path: str) -> str:
    directory = os.path.dirname(path) or "."
    if isinstance(exc, PermissionError):
        return (f"Can't write to {directory}: permission denied. Changes are "
                f"not being saved. Make the appdata folder writable by the "
                f"container (user {os.geteuid()}).")
    return f"Can't write {path}: {exc.strerror or exc}. Changes are not being saved."


def _fsync_dir(directory: str) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return  # not supported everywhere; the file itself is already synced
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def save_json(path: str, data, **dump_kwargs) -> None:
    """Write data to path atomically and durably, keeping the old file as
    path.bak. Raises OSError (and records it) if the write fails."""
    directory = os.path.dirname(path) or "."
    tmp_path = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-",
                                        suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, **dump_kwargs)
            fh.flush()
            os.fsync(fh.fileno())
        if os.path.exists(path):
            os.replace(path, path + ".bak")
        os.replace(tmp_path, path)
        tmp_path = None
        _fsync_dir(directory)
    except OSError as exc:
        message = _describe(exc, path)
        if storage_error() != message:
            log.error("%s (%s)", message, exc)
        _set_error(message)
        raise
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    _set_error(None)


def _read(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_json(path: str, what: str):
    """Read path, falling back to path.bak if it is missing or unreadable.
    Returns None when neither exists (a fresh install) or both are bad."""
    try:
        return _read(path)
    except FileNotFoundError:
        problem = None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        problem = exc
    try:
        data = _read(path + ".bak")
    except FileNotFoundError:
        data = None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        log.warning("Backup %s file %s.bak is unreadable too (%s)", what, path, exc)
        data = None
    if problem is not None:
        _keep_aside(path, what, problem, recovered=data is not None)
    elif data is not None:
        log.warning("%s file %s is missing; restored from %s.bak",
                    what.capitalize(), path, path)
    return data


def _keep_aside(path: str, what: str, problem: Exception, recovered: bool) -> None:
    """Move an unreadable file out of the way so the next save can't destroy
    what might be left in it."""
    aside = path + ".corrupt"
    try:
        os.replace(path, aside)
        kept = f"; the unreadable file was kept as {aside}"
    except OSError:
        kept = ""
    outcome = (f"restored from {path}.bak" if recovered
               else "starting from defaults")
    log.warning("Could not read %s file %s (%s); %s%s",
                what, path, problem, outcome, kept)


def check_writable(directory: str) -> str | None:
    """Try a small write in directory. Returns why it failed, or None."""
    probe = os.path.join(directory, ".write-test")
    try:
        os.makedirs(directory, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.unlink(probe)
    except OSError as exc:
        message = _describe(exc, probe)
        _set_error(message)
        return message
    return None
