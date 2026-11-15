"""Run as PUID:PGID with a config folder that user can write.

The image starts as root so it can fix the ownership of /config, then drops
to PUID:PGID (default 99:100, Unraid's nobody:users) before anything else
runs. Docker creates a missing appdata folder owned by root; without this a
container running as nobody couldn't save anything there.

Started as a non-root user (docker run --user ...), this does nothing.
"""

import logging
import os

log = logging.getLogger(__name__)


def _id_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("%s=%r is not a number; using %d", name, raw, default)
        return default
    return value if value >= 0 else default


def _take_ownership(directory: str, uid: int, gid: int) -> int:
    """Give directory and everything in it to uid:gid. Returns how many
    entries changed. Symlinks are changed themselves, never followed."""
    changed = 0
    os.makedirs(directory, exist_ok=True)
    for root, dirs, files in os.walk(directory):
        paths = [root] + [os.path.join(root, f) for f in files] \
            + [os.path.join(root, d) for d in dirs if os.path.islink(os.path.join(root, d))]
        for path in paths:
            try:
                st = os.lstat(path)
                if st.st_uid != uid or st.st_gid != gid:
                    os.lchown(path, uid, gid)
                    changed += 1
            except OSError as exc:
                log.warning("Could not change the owner of %s: %s", path, exc)
    return changed


def drop_privileges(directories) -> None:
    if os.geteuid() != 0:
        return
    uid = _id_from_env("PUID", 99)
    gid = _id_from_env("PGID", 100)
    for directory in dict.fromkeys(directories):
        try:
            changed = _take_ownership(directory, uid, gid)
        except OSError as exc:
            log.warning("Could not prepare %s: %s", directory, exc)
            continue
        if changed:
            log.info("Gave %d file(s) in %s to %d:%d", changed, directory, uid, gid)
    if uid == 0:
        log.warning("PUID is 0: running as root")
        return
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    log.info("Running as %d:%d", uid, gid)
