import logging

import requests

from ..util import normalize_title

log = logging.getLogger(__name__)


class ArrError(Exception):
    pass


class ArrClient:
    """Shared plumbing for the Radarr and Sonarr v3 APIs."""

    app_name = "arr"

    def __init__(self, base_url: str, api_key: str,
                 quality_profile: str = "", root_folder: str = ""):
        self.base_url = base_url.rstrip("/")
        self.quality_profile = quality_profile
        self.root_folder = root_folder
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key})
        self._quality_profile_id: int | None = None
        self._root_folder_path: str | None = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v3/{path.lstrip('/')}"

    def _get(self, path: str, **params):
        resp = self.session.get(self._url(path), params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict):
        resp = self.session.post(self._url(path), json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def check_connection(self) -> None:
        try:
            status = self._get("system/status")
        except requests.RequestException as exc:
            raise ArrError(f"Cannot reach {self.app_name} at {self.base_url}: {exc}") from exc
        log.info("Connected to %s %s at %s",
                 status.get("appName", self.app_name),
                 status.get("version", "?"), self.base_url)

    def resolve_quality_profile_id(self) -> int:
        if self._quality_profile_id is not None:
            return self._quality_profile_id
        profiles = self._get("qualityprofile")
        if not profiles:
            raise ArrError(f"{self.app_name} has no quality profiles configured")
        wanted = self.quality_profile
        if wanted:
            for profile in profiles:
                if str(profile.get("id")) == wanted or \
                        profile.get("name", "").lower() == wanted.lower():
                    self._quality_profile_id = profile["id"]
                    break
            else:
                names = ", ".join(p.get("name", "?") for p in profiles)
                raise ArrError(
                    f"{self.app_name} quality profile {wanted!r} not found "
                    f"(available: {names})")
        else:
            self._quality_profile_id = profiles[0]["id"]
            log.info("%s: no quality profile configured, using %r",
                     self.app_name, profiles[0].get("name"))
        return self._quality_profile_id

    def resolve_root_folder(self) -> str:
        if self._root_folder_path is not None:
            return self._root_folder_path
        folders = self._get("rootfolder")
        if not folders:
            raise ArrError(f"{self.app_name} has no root folders configured")
        wanted = self.root_folder
        if wanted:
            for folder in folders:
                if folder.get("path", "").rstrip("/") == wanted.rstrip("/"):
                    self._root_folder_path = folder["path"]
                    break
            else:
                paths = ", ".join(f.get("path", "?") for f in folders)
                raise ArrError(
                    f"{self.app_name} root folder {wanted!r} not found "
                    f"(available: {paths})")
        else:
            self._root_folder_path = folders[0]["path"]
            log.info("%s: no root folder configured, using %r",
                     self.app_name, folders[0].get("path"))
        return self._root_folder_path


def is_already_exists_error(exc: requests.HTTPError) -> bool:
    """Radarr/Sonarr reply 400 with a validation message when the title is
    already in the library; treat that as success rather than failure."""
    resp = exc.response
    if resp is None or resp.status_code != 400:
        return False
    body = resp.text.lower()
    return "already been added" in body or "already exists" in body


def pick_best(candidates: list[dict], title: str, year: int | None,
              tmdb_id: int | None = None) -> dict | None:
    """Choose the best lookup result for a discovered item.

    Preference order: exact TMDB id, exact normalized title with matching
    year (+/-1 to absorb festival vs wide-release dates), exact normalized
    title with no year to compare against.
    """
    if not candidates:
        return None
    if tmdb_id:
        for cand in candidates:
            if cand.get("tmdbId") == tmdb_id:
                return cand
    wanted = normalize_title(title)
    title_matches = [c for c in candidates
                     if normalize_title(c.get("title", "")) == wanted]
    if not title_matches:
        return None
    if year:
        for cand in title_matches:
            cand_year = cand.get("year")
            if isinstance(cand_year, int) and abs(cand_year - year) <= 1:
                return cand
        return None
    return title_matches[0]
