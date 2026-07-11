import re


def normalize_title(title: str) -> str:
    """Lowercase a title and collapse everything that isn't a letter or digit,
    so 'Dune: Part Two' and 'dune part two' compare equal."""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
