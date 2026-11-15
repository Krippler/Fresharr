"""Last-run status persisted for the web UI and for scheduling across
container restarts."""

from .storage import load_json, save_json


def load_status(path: str) -> dict:
    data = load_json(path, "status")
    return data if isinstance(data, dict) else {}


def save_status(path: str, data: dict) -> None:
    save_json(path, data, indent=2)
