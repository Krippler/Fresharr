"""Genre and network filters.

Discovery sites, Radarr and Sonarr all name genres and networks slightly
differently ("Sci-Fi & Fantasy", "science-fiction", "Science Fiction";
"HBO Max", "Max"). Everything is matched through the canonical ids below so
one setting covers every spelling.

Rules are enforced twice: when collecting candidates (with whatever the site
reported) and again at add time against Radarr/Sonarr's own metadata, which
covers the sites that report nothing. A title whose genres or network are
unknown passes, the same as the language filter: dropping it would silence
whole sources.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field

from .models import MOVIE

# id, label, TMDB movie genre ids, TMDB TV genre ids, Trakt slugs,
# AniList genre names, other spellings seen in Radarr/Sonarr/Jikan.
_GENRES = [
    ("action", "Action", [28], [10759], ["action"], ["Action"], ["action & adventure"]),
    ("adventure", "Adventure", [12], [10759], ["adventure"], ["Adventure"],
     ["action & adventure"]),
    ("animation", "Animation", [16], [16], ["animation"], [], []),
    ("comedy", "Comedy", [35], [35], ["comedy"], ["Comedy"], []),
    ("crime", "Crime", [80], [80], ["crime"], [], []),
    ("documentary", "Documentary", [99], [99], ["documentary"], [], ["documentaries"]),
    ("drama", "Drama", [18], [18], ["drama"], ["Drama"], []),
    ("family", "Family", [10751], [10751], ["family"], [], []),
    ("fantasy", "Fantasy", [14], [10765], ["fantasy"], ["Fantasy"], ["sci-fi & fantasy"]),
    ("history", "History", [36], [], ["history"], [], ["historical"]),
    ("horror", "Horror", [27], [], ["horror"], ["Horror"], []),
    ("kids", "Kids", [], [10762], ["children"], [], ["children", "kids"]),
    ("music", "Music", [10402], [], ["music", "musical"], ["Music"], ["musical"]),
    ("mystery", "Mystery", [9648], [9648], ["mystery"], ["Mystery"], []),
    ("news", "News", [], [10763], ["news"], [], []),
    ("reality", "Reality", [], [10764], ["reality"], [], ["reality-tv", "reality tv"]),
    ("romance", "Romance", [10749], [], ["romance"], ["Romance"], []),
    ("science-fiction", "Science Fiction", [878], [10765], ["science-fiction"],
     ["Sci-Fi"], ["sci-fi", "scifi", "sci-fi & fantasy"]),
    ("soap", "Soap", [], [10766], ["soap"], [], []),
    ("sport", "Sport", [], [], [], ["Sports"], ["sports"]),
    ("talk", "Talk Show", [], [10767], ["talk-show"], [], ["talk"]),
    ("game-show", "Game Show", [], [], ["game-show"], [], []),
    ("thriller", "Thriller", [53], [], ["thriller", "suspense"], ["Thriller"],
     ["suspense"]),
    ("war", "War", [10752], [10768], ["war"], [], ["war & politics"]),
    ("western", "Western", [37], [37], ["western"], [], []),
    # Anime-leaning genres. AniList and MyAnimeList report these; Sonarr
    # mostly doesn't, so they are enforced from the site's data.
    ("slice-of-life", "Slice of Life", [], [], [], ["Slice of Life"], []),
    ("supernatural", "Supernatural", [], [], [], ["Supernatural"], []),
    ("psychological", "Psychological", [], [], [], ["Psychological"], []),
    ("mecha", "Mecha", [], [], [], ["Mecha"], []),
    ("ecchi", "Ecchi", [], [], [], ["Ecchi"], []),
]

# id, label, TMDB network id, other spellings seen in Sonarr/Trakt.
_NETWORKS = [
    ("netflix", "Netflix", 213, []),
    ("hbo", "HBO", 49, []),
    ("max", "HBO Max / Max", 3186, ["hbo max", "max"]),
    ("hulu", "Hulu", 453, []),
    ("disney-plus", "Disney+", 2739, ["disney+", "disney plus"]),
    ("apple-tv", "Apple TV+", 2552, ["apple tv+", "apple tv", "apple tv plus"]),
    ("prime-video", "Prime Video", 1024,
     ["prime video", "amazon", "amazon prime video", "amazon studios"]),
    ("paramount-plus", "Paramount+", 4330,
     ["paramount+", "paramount plus", "cbs all access"]),
    ("peacock", "Peacock", 3353, []),
    ("showtime", "Showtime", 67, []),
    ("starz", "Starz", 318, []),
    ("cinemax", "Cinemax", 359, []),
    ("nbc", "NBC", 6, []),
    ("abc", "ABC", 2, []),
    ("cbs", "CBS", 16, []),
    ("fox", "FOX", 19, []),
    ("the-cw", "The CW", 71, ["the cw", "cw"]),
    ("fx", "FX", 88, []),
    ("amc", "AMC", 174, []),
    ("tnt", "TNT", 41, []),
    ("tbs", "TBS", 68, []),
    ("usa-network", "USA Network", 30, ["usa network", "usa"]),
    ("syfy", "Syfy", 77, []),
    ("bravo", "Bravo", 74, []),
    ("mtv", "MTV", 33, []),
    ("comedy-central", "Comedy Central", 47, []),
    ("adult-swim", "Adult Swim", 80, ["adult swim", "[adult swim]"]),
    ("cartoon-network", "Cartoon Network", 56, []),
    ("pbs", "PBS", 14, []),
    ("discovery", "Discovery", 64, ["discovery", "discovery channel"]),
    ("national-geographic", "National Geographic", 43,
     ["national geographic", "national geographic channel", "nat geo"]),
    ("history-channel", "History", 65, ["history", "history channel"]),
    ("bbc-one", "BBC One", 4, []),
    ("crunchyroll", "Crunchyroll", 1112, []),
]

GENRE_OPTIONS = [{"id": g[0], "label": g[1]} for g in _GENRES]
NETWORK_OPTIONS = [{"id": n[0], "label": n[1]} for n in _NETWORKS]
GENRE_IDS = frozenset(g[0] for g in _GENRES)
NETWORK_IDS = frozenset(n[0] for n in _NETWORKS)

# Filters are kept per content kind: genres for movies, TV and anime;
# networks only for series (Radarr's movie metadata has no network).
GENRE_KINDS = ("movie", "tv", "anime")
NETWORK_KINDS = ("tv", "anime")

# A network not in the list above can be typed in by name.
CUSTOM_NETWORK_RE = re.compile(r"^[\w .&+'!:()/-]{1,40}$")


def _norm(text: str) -> str:
    """Comparison form of a genre/network name: lowercase, '+' spelled out,
    a trailing country tag like "(US)" dropped, punctuation removed."""
    text = re.sub(r"\s*\([a-z]{2,3}\)\s*$", "", str(text).strip().lower())
    text = text.replace("&", " and ").replace("+", " plus ")
    return re.sub(r"[^a-z0-9]+", "", text)


def _build_alias_map(rows, names_of) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for row in rows:
        for name in names_of(row):
            aliases.setdefault(_norm(name), set()).add(row[0])
    return aliases


_GENRE_ALIASES = _build_alias_map(
    _GENRES, lambda g: [g[0], g[1], *g[4], *g[5], *g[6]])
_NETWORK_ALIASES = _build_alias_map(
    _NETWORKS, lambda n: [n[0], n[1], *n[3]])

_TMDB_MOVIE_GENRES = {g[0]: g[2] for g in _GENRES}
_TMDB_TV_GENRES = {g[0]: g[3] for g in _GENRES}
_TMDB_NETWORK = {n[0]: n[2] for n in _NETWORKS}
_TRAKT_GENRES = {g[0]: g[4] for g in _GENRES}
_ANILIST_GENRES = {g[0]: g[5] for g in _GENRES}


def canonical_genres(names) -> set[str]:
    """Canonical genre ids for a list of genre names from any site or app.
    Combined names ("Action & Adventure") yield both; unknown names nothing."""
    out: set[str] = set()
    for name in names or ():
        if isinstance(name, str):
            out |= _GENRE_ALIASES.get(_norm(name), set())
    return out


def tmdb_genre_names(genre_ids, media_type: str) -> tuple[str, ...]:
    """Canonical genre ids for TMDB's numeric genre_ids."""
    table = _TMDB_MOVIE_GENRES if media_type == MOVIE else _TMDB_TV_GENRES
    wanted = {gid for gid in genre_ids or () if isinstance(gid, int)}
    return tuple(sorted(g for g, ids in table.items() if wanted & set(ids)))


def _network_keys(name: str) -> set[str]:
    """What a network name matches: its canonical id if it's a known one,
    and always its normalised text (so typed-in names still match)."""
    key = _norm(name)
    return _NETWORK_ALIASES.get(key, set()) | {key}


def _setting_keys(entries) -> set[str]:
    keys: set[str] = set()
    for entry in entries:
        keys |= {entry} if entry in NETWORK_IDS else _network_keys(entry)
    return keys


@dataclass(frozen=True)
class Rules:
    """Everything that can filter one kind of title (movie, TV or anime)."""
    languages: tuple[str, ...] = ()
    include_genres: frozenset = frozenset()
    exclude_genres: frozenset = frozenset()
    include_networks: tuple[str, ...] = ()
    exclude_networks: tuple[str, ...] = ()
    _include_keys: frozenset = field(default=frozenset(), repr=False, compare=False)
    _exclude_keys: frozenset = field(default=frozenset(), repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "_include_keys",
                           frozenset(_setting_keys(self.include_networks)))
        object.__setattr__(self, "_exclude_keys",
                           frozenset(_setting_keys(self.exclude_networks)))

    @property
    def active(self) -> bool:
        return bool(self.languages or self.include_genres or self.exclude_genres
                    or self.include_networks or self.exclude_networks)

    def genre_reason(self, genres) -> str | None:
        """Why these genre names are filtered out, or None if they pass."""
        if not (self.include_genres or self.exclude_genres):
            return None
        found = canonical_genres(genres)
        blocked = found & self.exclude_genres
        if blocked:
            return "genre " + ", ".join(sorted(blocked)) + " is excluded"
        if self.include_genres and found and not (found & self.include_genres):
            return ("genres " + ", ".join(sorted(found))
                    + " are not in the selected genres")
        return None

    def network_reason(self, network: str | None) -> str | None:
        """Why this network is filtered out, or None if it passes."""
        if not network or not (self._include_keys or self._exclude_keys):
            return None
        keys = _network_keys(network)
        if keys & self._exclude_keys:
            return f"network {network} is excluded"
        if self._include_keys and not (keys & self._include_keys):
            return f"network {network} is not in the selected networks"
        return None

    def signature(self) -> str:
        """Short fingerprint, stored with filtered titles so a change to the
        filters gets them looked at again straight away."""
        blob = json.dumps([sorted(self.languages), sorted(self.include_genres),
                           sorted(self.exclude_genres),
                           sorted(self.include_networks),
                           sorted(self.exclude_networks)])
        return hashlib.sha1(blob.encode()).hexdigest()[:12]

    # ── Pushing filters down to the sites' own search ─────────────────────
    # Only where the site can express the filter exactly, or as a superset
    # that the later check narrows; never anything that could drop a title
    # the user asked for.

    def tmdb_params(self, media_type: str, series: bool) -> dict:
        table = _TMDB_MOVIE_GENRES if media_type == MOVIE else _TMDB_TV_GENRES
        params: dict[str, str] = {}
        if self.include_genres and all(table.get(g) for g in self.include_genres):
            ids = sorted({i for g in self.include_genres for i in table[g]})
            params["with_genres"] = "|".join(map(str, ids))
        if self.exclude_genres:
            # A TMDB genre shared between two of ours ("Sci-Fi & Fantasy") is
            # only excluded when both are.
            covered = {}
            for g, ids in table.items():
                for i in ids:
                    covered.setdefault(i, set()).add(g)
            without = sorted(i for i, gs in covered.items()
                             if gs <= self.exclude_genres and not _shared(i))
            if without:
                params["without_genres"] = ",".join(map(str, without))
        if series and self.include_networks and \
                all(n in _TMDB_NETWORK for n in self.include_networks):
            params["with_networks"] = "|".join(
                str(_TMDB_NETWORK[n]) for n in sorted(self.include_networks))
        return params

    def trakt_params(self) -> dict:
        if self.include_genres and all(_TRAKT_GENRES.get(g)
                                       for g in self.include_genres):
            slugs = sorted({s for g in self.include_genres for s in _TRAKT_GENRES[g]})
            return {"genres": ",".join(slugs)}
        return {}

    def anilist_variables(self) -> dict:
        variables: dict = {}
        if self.include_genres and all(_ANILIST_GENRES.get(g)
                                       for g in self.include_genres):
            variables["genreIn"] = sorted(
                {n for g in self.include_genres for n in _ANILIST_GENRES[g]})
        excluded = sorted({n for g in self.exclude_genres
                           for n in _ANILIST_GENRES.get(g, [])})
        if excluded:
            variables["genreNotIn"] = excluded
        return variables


# TMDB genres that stand for more than one thing we filter on, where the
# other half has no id of its own ("War & Politics" is also politics).
_SHARED_TMDB_GENRES = {10768}


def _shared(tmdb_id: int) -> bool:
    return tmdb_id in _SHARED_TMDB_GENRES


def rules_for(settings, kind: str) -> Rules:
    """The Rules for one content kind from the web-UI settings."""
    languages = getattr(settings, f"{kind}_languages", None) or []
    genres = (getattr(settings, "genre_filters", None) or {}).get(kind, {})
    networks = (getattr(settings, "network_filters", None) or {}).get(kind, {})
    return Rules(
        languages=tuple(lang.lower() for lang in languages),
        include_genres=frozenset(genres.get("include", ())),
        exclude_genres=frozenset(genres.get("exclude", ())),
        include_networks=tuple(networks.get("include", ())),
        exclude_networks=tuple(networks.get("exclude", ())),
    )
