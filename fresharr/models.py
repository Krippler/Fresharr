from dataclasses import dataclass

from .util import normalize_title

MOVIE = "movie"
TV = "tv"


@dataclass(frozen=True)
class MediaItem:
    title: str
    media_type: str  # MOVIE or TV
    source: str
    year: int | None = None
    critics_score: int | None = None
    audience_score: int | None = None
    tmdb_id: int | None = None
    url: str | None = None
    # Alternate titles (e.g. romaji vs English for anime) tried during
    # Radarr/Sonarr lookup when the primary title doesn't match.
    alt_titles: tuple[str, ...] = ()
    # Anime series are added to Sonarr with seriesType "anime" so episodes
    # get absolute numbering.
    anime: bool = False

    @property
    def key(self) -> str:
        """Stable identity used for cross-source dedupe and the seen-state file.

        Title+year based (not source IDs) so the same film discovered on
        Rotten Tomatoes and TMDB collapses to one entry.
        """
        year = self.year if self.year is not None else "any"
        return f"{self.media_type}:{normalize_title(self.title)}:{year}"

    def describe(self) -> str:
        parts = [self.title]
        if self.year:
            parts.append(f"({self.year})")
        scores = []
        if self.critics_score is not None:
            scores.append(f"critics {self.critics_score}%")
        if self.audience_score is not None:
            scores.append(f"audience {self.audience_score}%")
        if scores:
            parts.append("[" + ", ".join(scores) + "]")
        parts.append(f"<{self.source}>")
        return " ".join(parts)
