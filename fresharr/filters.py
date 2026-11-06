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
import unicodedata
from dataclasses import dataclass, field

from .models import MOVIE

# id, label, TMDB movie genre ids, TMDB TV genre ids, Trakt slugs,
# AniList genre names, other spellings seen in Radarr/Sonarr/Jikan.
# Kept in alphabetical order of label, which is the order the UI shows.
# Some, like Isekai or Mecha, are mostly reported by AniList and MyAnimeList
# only, so they are enforced from the site's data.
_GENRES = [
    ("action", "Action", [28], [10759], ["action"], ["Action"], ["action & adventure"]),
    ("adventure", "Adventure", [12], [10759], ["adventure"], ["Adventure"],
     ["action & adventure"]),
    ("animation", "Animation", [16], [16], ["animation"], [], []),
    ("anime", "Anime", [], [], ["anime"], [], []),
    ("biography", "Biography", [], [], ["biography"], [], []),
    ("boys-love", "Boys Love", [], [], [], [], []),
    ("comedy", "Comedy", [35], [35], ["comedy"], ["Comedy"], []),
    ("crime", "Crime", [80], [80], ["crime"], [], []),
    ("documentary", "Documentary", [99], [99], ["documentary"], [], ["documentaries"]),
    ("drama", "Drama", [18], [18], ["drama"], ["Drama"], []),
    ("ecchi", "Ecchi", [], [], [], ["Ecchi"], []),
    ("family", "Family", [10751], [10751], ["family"], [], []),
    ("fantasy", "Fantasy", [14], [10765], ["fantasy"], ["Fantasy"], ["sci-fi & fantasy"]),
    ("food", "Food", [], [], [], [], ["gourmet", "cooking"]),
    ("game-show", "Game Show", [], [], ["game-show"], [], []),
    ("girls-love", "Girls Love", [], [], [], [], []),
    ("history", "History", [36], [], ["history"], [], ["historical"]),
    ("holiday", "Holiday", [], [], ["holiday"], [], ["christmas"]),
    ("home-and-garden", "Home & Garden", [], [], ["home-and-garden"], [], []),
    ("horror", "Horror", [27], [], ["horror"], ["Horror"], []),
    ("isekai", "Isekai", [], [], [], [], []),
    ("kids", "Kids", [], [10762], ["children"], [], ["children", "kids"]),
    ("mahou-shoujo", "Mahou Shoujo", [], [], [], ["Mahou Shoujo"], ["magical girl"]),
    ("martial-arts", "Martial Arts", [], [], [], [], []),
    ("mecha", "Mecha", [], [], [], ["Mecha"], []),
    ("music", "Music", [10402], [], ["music", "musical"], ["Music"], ["musical"]),
    ("mystery", "Mystery", [9648], [9648], ["mystery"], ["Mystery"], []),
    ("news", "News", [], [10763], ["news"], [], []),
    ("psychological", "Psychological", [], [], [], ["Psychological"], []),
    ("reality", "Reality", [], [10764], ["reality"], [], ["reality-tv", "reality tv"]),
    ("romance", "Romance", [10749], [], ["romance"], ["Romance"], []),
    ("school", "School", [], [], [], [], []),
    ("science-fiction", "Science Fiction", [878], [10765], ["science-fiction"],
     ["Sci-Fi"], ["sci-fi", "scifi", "sci-fi & fantasy"]),
    ("slice-of-life", "Slice of Life", [], [], [], ["Slice of Life"], ["iyashikei"]),
    ("soap", "Soap", [], [10766], ["soap"], [], []),
    ("sport", "Sport", [], [], [], ["Sports"], ["sports"]),
    ("superhero", "Superhero", [], [], ["superhero"], [], ["super power"]),
    ("supernatural", "Supernatural", [], [], [], ["Supernatural"], []),
    ("talk", "Talk Show", [], [10767], ["talk-show"], [], ["talk"]),
    ("thriller", "Thriller", [53], [], ["thriller", "suspense"], ["Thriller"],
     ["suspense"]),
    ("travel", "Travel", [], [], [], [], []),
    ("tv-movie", "TV Movie", [10770], [], [], [], []),
    ("war", "War", [10752], [10768], ["war"], [], ["war & politics", "military"]),
    ("western", "Western", [37], [37], ["western"], [], []),
]

# ISO 639-1 code, label, other names Radarr/Sonarr give the language.
# Alphabetical by label.
_LANGUAGES = [
    ("ar", "Arabic", []),
    ("bn", "Bengali", []),
    ("bg", "Bulgarian", []),
    ("ca", "Catalan", []),
    ("zh", "Chinese", ["mandarin", "cantonese"]),
    ("hr", "Croatian", []),
    ("cs", "Czech", []),
    ("da", "Danish", []),
    ("nl", "Dutch", ["flemish"]),
    ("en", "English", []),
    ("et", "Estonian", []),
    ("tl", "Filipino", ["tagalog"]),
    ("fi", "Finnish", []),
    ("fr", "French", []),
    ("de", "German", []),
    ("el", "Greek", []),
    ("he", "Hebrew", []),
    ("hi", "Hindi", []),
    ("hu", "Hungarian", []),
    ("is", "Icelandic", []),
    ("id", "Indonesian", []),
    ("it", "Italian", []),
    ("ja", "Japanese", []),
    ("kn", "Kannada", []),
    ("ko", "Korean", []),
    ("lv", "Latvian", []),
    ("lt", "Lithuanian", []),
    ("ms", "Malay", []),
    ("ml", "Malayalam", []),
    ("mr", "Marathi", []),
    ("no", "Norwegian", ["norwegian bokmal", "norwegian bokmål"]),
    ("fa", "Persian", ["farsi"]),
    ("pl", "Polish", []),
    ("pt", "Portuguese", ["portuguese (brazil)", "brazilian portuguese"]),
    ("ro", "Romanian", []),
    ("ru", "Russian", []),
    ("sr", "Serbian", []),
    ("sk", "Slovak", []),
    ("es", "Spanish", ["spanish (latino)", "latin american spanish"]),
    ("sv", "Swedish", []),
    ("ta", "Tamil", []),
    ("te", "Telugu", []),
    ("th", "Thai", []),
    ("tr", "Turkish", []),
    ("uk", "Ukrainian", []),
    ("ur", "Urdu", []),
    ("vi", "Vietnamese", []),
]

LANGUAGE_OPTIONS = [{"code": code, "label": label}
                    for code, label, _ in sorted(_LANGUAGES, key=lambda r: r[1])]
# Radarr/Sonarr report a title's original language by English name.
LANGUAGE_NAME_TO_CODE = {name: code for code, label, others in _LANGUAGES
                         for name in (label.lower(), *others)}
# Codes some sites use in place of the ISO 639-1 one: TMDB gives Cantonese
# as "cn" and some Norwegian as "nb"; older data has "iw" and "in".
_LANGUAGE_CODE_ALIASES = {"cn": "zh", "nb": "no", "nn": "no", "fil": "tl",
                          "iw": "he", "in": "id"}


def normalize_language(code: str | None) -> str | None:
    """A site's language code in the form the filter settings use."""
    if not code:
        return None
    code = code.strip().lower()
    return _LANGUAGE_CODE_ALIASES.get(code, code)


# id, label, TMDB network ids, other spellings seen in Sonarr/Trakt.
# Alphabetical by label. TMDB ids were checked against each network's TMDB
# page (name and homepage); a network TMDB splits in two (MGM+ and its old
# name Epix, or TBS in the US and Japan) lists both.
_NETWORKS = [
    ("a-and-e", "A&E", [129], []),
    ("abc", "ABC", [2], []),
    ("acorn-tv", "Acorn TV", [2697], []),
    ("adult-swim", "Adult Swim", [80], ["adult swim", "[adult swim]"]),
    ("amc", "AMC", [174], []),
    ("amc-plus", "AMC+", [4661], []),
    ("animal-planet", "Animal Planet", [91], []),
    ("apple-tv", "Apple TV+", [2552], ["apple tv+", "apple tv", "apple tv plus"]),
    ("arte", "ARTE", [662], []),
    ("at-x", "AT-X", [173], []),
    ("bbc-america", "BBC America", [493], []),
    ("bbc-four", "BBC Four", [100], []),
    ("bbc-iplayer", "BBC iPlayer", [1155], []),
    ("bbc-one", "BBC One", [4], []),
    ("bbc-three", "BBC Three", [3], []),
    ("bbc-two", "BBC Two", [332], []),
    ("bet", "BET", [24], []),
    ("bravo", "Bravo", [74], []),
    ("britbox", "BritBox", [4025], []),
    ("canal-plus", "Canal+", [285], []),
    ("cartoon-network", "Cartoon Network", [56], []),
    ("cbc", "CBC", [23], ["cbc television"]),
    ("cbs", "CBS", [16], []),
    ("channel-4", "Channel 4", [26], []),
    ("channel-5", "Channel 5", [99], ["5"]),
    ("cinemax", "Cinemax", [359], []),
    ("comedy-central", "Comedy Central", [47], []),
    ("crave", "Crave", [1344], []),
    ("crunchyroll", "Crunchyroll", [1112], []),
    ("ctv", "CTV", [110], []),
    ("cw-seed", "CW Seed", [1049], []),
    ("das-erste", "Das Erste (ARD)", [308], ["das erste", "ard"]),
    ("discovery", "Discovery", [64], ["discovery", "discovery channel"]),
    ("discovery-plus", "Discovery+", [4353], []),
    ("disney-channel", "Disney Channel", [54], []),
    ("disney-xd", "Disney XD", [44], []),
    ("disney-plus", "Disney+", [2739], ["disney+", "disney plus"]),
    ("e", "E!", [76], ["e! entertainment"]),
    ("food-network", "Food Network", [143], []),
    ("fox", "FOX", [19], []),
    ("freeform", "Freeform", [1267], ["abc family"]),
    ("freevee", "Freevee", [5865], ["amazon freevee", "imdb tv"]),
    ("fuji-tv", "Fuji TV", [1], []),
    ("fx", "FX", [88], []),
    ("fxx", "FXX", [1035], []),
    ("hallmark", "Hallmark Channel", [384], []),
    ("hbo", "HBO", [49], []),
    ("max", "HBO Max / Max", [3186], ["hbo max", "max"]),
    ("hgtv", "HGTV", [210], []),
    ("hidive", "HIDIVE", [7645], []),
    ("history-channel", "History", [65], ["history", "history channel"]),
    ("hulu", "Hulu", [453], []),
    ("ifc", "IFC", [124], []),
    ("investigation-discovery", "Investigation Discovery", [244], ["id"]),
    ("itv", "ITV1", [9], ["itv"]),
    ("itvx", "ITVX", [5871], []),
    ("jtbc", "JTBC", [885], []),
    ("kbs2", "KBS2", [342], []),
    ("lifetime", "Lifetime", [34], []),
    ("mbc", "MBC", [97], []),
    ("mbs", "MBS", [94], []),
    ("mgm-plus", "MGM+", [6219, 922], ["epix"]),
    ("mtv", "MTV", [33], []),
    ("nat-geo-wild", "Nat Geo Wild", [1043], []),
    ("national-geographic", "National Geographic", [43],
     ["national geographic", "national geographic channel", "nat geo"]),
    ("nbc", "NBC", [6], []),
    ("netflix", "Netflix", [213], []),
    ("nickelodeon", "Nickelodeon", [13], ["nick"]),
    ("nippon-tv", "Nippon TV", [57], ["ntv"]),
    ("oxygen", "Oxygen", [132], []),
    ("paramount-network", "Paramount Network", [2076], ["spike"]),
    ("paramount-plus", "Paramount+", [4330],
     ["paramount+", "paramount plus", "cbs all access"]),
    ("pbs", "PBS", [14], []),
    ("peacock", "Peacock", [3353], []),
    ("prime-video", "Prime Video", [1024],
     ["prime video", "amazon", "amazon prime video", "amazon studios"]),
    ("rai-1", "Rai 1", [533], []),
    ("roku-channel", "Roku Channel", [4692], ["the roku channel"]),
    ("science-channel", "Science Channel", [226], ["science"]),
    ("showtime", "Showtime", [67], []),
    ("shudder", "Shudder", [2949], []),
    ("sky-atlantic", "Sky Atlantic", [1063], []),
    ("sky-one", "Sky One / Sky Max", [214], ["sky one", "sky max"]),
    ("stan", "Stan", [1255], []),
    ("starz", "Starz", [318], []),
    ("sundance-tv", "SundanceTV", [270], ["sundance tv"]),
    ("syfy", "Syfy", [77], []),
    ("tbs", "TBS", [68, 160], []),
    ("telemundo", "Telemundo", [193], []),
    ("tf1", "TF1", [290], []),
    ("the-cw", "The CW", [71], ["the cw", "cw"]),
    ("tlc", "TLC", [84], []),
    ("tnt", "TNT", [41], []),
    ("tokyo-mx", "Tokyo MX", [614], []),
    ("travel-channel", "Travel Channel", [209], []),
    ("trutv", "truTV", [364], []),
    ("tubi", "Tubi", [5187], []),
    ("tv-tokyo", "TV Tokyo", [98], []),
    ("tvn", "tvN", [866], []),
    ("univision", "Univision", [28], []),
    ("usa-network", "USA Network", [30], ["usa network", "usa"]),
    ("youtube", "YouTube", [247], []),
    ("youtube-premium", "YouTube Premium", [1436], ["youtube red"]),
    ("zdf", "ZDF", [31], []),
]

# id, label, TMDB company ids, other spellings. Radarr reports a film's
# studio as TMDB's first production company, so the spellings cover TMDB's
# own names. Ids checked against each company's TMDB page (name and film
# count); where TMDB has the same studio under more than one id (renamed, or
# entered twice), all are listed.
_STUDIOS = [
    ("20th-century", "20th Century Studios / Fox", [127928, 25],
     ["20th century studios", "20th century fox", "twentieth century fox"]),
    ("a24", "A24", [41077, 293354], []),
    ("aardman", "Aardman", [297], ["aardman animations"]),
    ("amazon-mgm", "Amazon MGM Studios", [210099, 20580], ["amazon studios"]),
    ("amblin", "Amblin Entertainment", [56], []),
    ("annapurna", "Annapurna Pictures", [13184, 117057], []),
    ("apple-studios", "Apple Studios", [194232], ["apple original films"]),
    ("atomic-monster", "Atomic Monster", [76907], []),
    ("bad-robot", "Bad Robot", [11461], ["bad robot productions"]),
    ("bbc-film", "BBC Film", [288], ["bbc films"]),
    ("bleecker-street", "Bleecker Street", [167986], []),
    ("blue-sky", "Blue Sky Studios", [9383], []),
    ("blumhouse", "Blumhouse Productions", [3172], ["blumhouse"]),
    ("bones", "Bones", [2849], []),
    ("castle-rock", "Castle Rock Entertainment", [97], []),
    ("columbia", "Columbia Pictures", [5], []),
    ("comix-wave", "CoMix Wave Films", [3756], []),
    ("constantin", "Constantin Film", [47], []),
    ("dc", "DC Studios", [184898, 128064, 9993],
     ["dc films", "dc entertainment", "dc comics"]),
    ("dimension", "Dimension Films", [7405], []),
    ("dreamworks-animation", "DreamWorks Animation", [521], []),
    ("dreamworks-pictures", "DreamWorks Pictures", [7], ["dreamworks", "dreamworks skg"]),
    ("eone", "Entertainment One", [8147], ["eone"]),
    ("film4", "Film4", [6705], ["film4 productions"]),
    ("focus", "Focus Features", [10146], []),
    ("gaumont", "Gaumont", [9], []),
    ("ghost-house", "Ghost House Pictures", [768], []),
    ("hammer", "Hammer Films", [1314], ["hammer film productions"]),
    ("hollywood-pictures", "Hollywood Pictures", [915], []),
    ("ifc-films", "IFC Films", [307], []),
    ("illumination", "Illumination", [6704], ["illumination entertainment"]),
    ("imagine", "Imagine Entertainment", [23], []),
    ("kyoto-animation", "Kyoto Animation", [5438], []),
    ("laika", "Laika", [11537], []),
    ("legendary", "Legendary Pictures", [923], ["legendary entertainment"]),
    ("lightstorm", "Lightstorm Entertainment", [574], []),
    ("lionsgate", "Lionsgate", [1632, 35], ["lions gate films", "lionsgate films"]),
    ("lucasfilm", "Lucasfilm", [1], ["lucasfilm ltd", "lucasfilm ltd."]),
    ("madhouse", "Madhouse", [3464], []),
    ("magnolia", "Magnolia Pictures", [1030], []),
    ("mappa", "MAPPA", [21444], []),
    ("marvel", "Marvel Studios", [420], []),
    ("mgm", "Metro-Goldwyn-Mayer", [21], ["mgm"]),
    ("miramax", "Miramax", [14], []),
    ("neon", "Neon", [90733], []),
    ("netflix", "Netflix", [178464, 185004], []),
    ("new-line", "New Line Cinema", [12], []),
    ("orion", "Orion Pictures", [41], []),
    ("paramount", "Paramount Pictures", [4], []),
    ("participant", "Participant", [6735], ["participant media"]),
    ("pathe", "Pathé", [7981], []),
    ("pixar", "Pixar", [3], ["pixar animation studios"]),
    ("plan-b", "Plan B Entertainment", [81], []),
    ("platinum-dunes", "Platinum Dunes", [2481], []),
    ("production-ig", "Production I.G", [529, 166624], []),
    ("regency", "Regency Enterprises", [508], []),
    ("relativity", "Relativity Media", [7295], []),
    ("roadside", "Roadside Attractions", [911], []),
    ("screen-gems", "Screen Gems", [3287], []),
    ("searchlight", "Searchlight Pictures", [127929, 43],
     ["fox searchlight pictures", "fox searchlight"]),
    ("skydance", "Skydance", [82819], ["skydance media", "skydance productions"]),
    ("sony-animation", "Sony Pictures Animation", [2251], []),
    ("sony-classics", "Sony Pictures Classics", [58], []),
    ("studio-ghibli", "Studio Ghibli", [10342], ["ghibli"]),
    ("studiocanal", "StudioCanal", [694, 218178, 106689], []),
    ("stx", "STXfilms", [47729], ["stx entertainment", "stx films"]),
    ("summit", "Summit Entertainment", [491], []),
    ("sunrise", "Sunrise", [3153], []),
    ("syncopy", "Syncopy", [9996], []),
    ("toei", "Toei Animation", [5542], []),
    ("toho", "Toho", [882], []),
    ("touchstone", "Touchstone Pictures", [9195], []),
    ("trigger", "Trigger", [50908], ["studio trigger"]),
    ("tristar", "TriStar Pictures", [559], []),
    ("ufotable", "ufotable", [5887], []),
    ("united-artists", "United Artists", [60], []),
    ("universal", "Universal Pictures", [33], []),
    ("village-roadshow", "Village Roadshow Pictures", [79], []),
    ("disney", "Walt Disney Pictures", [2], ["disney"]),
    ("disney-animation", "Walt Disney Animation Studios", [6125, 158526], []),
    ("warner-bros", "Warner Bros. Pictures", [174], ["warner bros", "warner bros."]),
    ("wit-studio", "Wit Studio", [31058], []),
    ("working-title", "Working Title Films", [10163, 221513], ["working title"]),
]


def _alphabetical(rows) -> list[dict]:
    return [{"id": r[0], "label": r[1]}
            for r in sorted(rows, key=lambda r: r[1].casefold())]


GENRE_OPTIONS = _alphabetical(_GENRES)
NETWORK_OPTIONS = _alphabetical(_NETWORKS)
STUDIO_OPTIONS = _alphabetical(_STUDIOS)
GENRE_IDS = frozenset(g[0] for g in _GENRES)
NETWORK_IDS = frozenset(n[0] for n in _NETWORKS)
STUDIO_IDS = frozenset(n[0] for n in _STUDIOS)

# Filters are kept per content kind: genres for movies, TV and anime;
# networks only for series (Radarr's movie metadata has no network).
GENRE_KINDS = ("movie", "tv", "anime")
NETWORK_KINDS = ("tv", "anime")
# Studios: movies only. Sonarr has no studio for a series.
STUDIO_KINDS = ("movie",)

# A network or studio not in the lists above can be typed in by name.
CUSTOM_NETWORK_RE = re.compile(r"^[\w .&+'!:()/-]{1,40}$")


def _norm(text: str) -> str:
    """Comparison form of a name: lowercase, accents dropped ("Pathé" is
    "pathe"), '+' spelled out, a trailing country tag like "(US)" dropped,
    punctuation removed."""
    text = unicodedata.normalize("NFKD", str(text).strip().lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s*\([a-z]{2,3}\)\s*$", "", text)
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
_STUDIO_ALIASES = _build_alias_map(
    _STUDIOS, lambda n: [n[0], n[1], *n[3]])

_TMDB_MOVIE_GENRES = {g[0]: g[2] for g in _GENRES}
_TMDB_TV_GENRES = {g[0]: g[3] for g in _GENRES}
_TMDB_NETWORK = {n[0]: n[2] for n in _NETWORKS}
_TMDB_COMPANY = {n[0]: n[2] for n in _STUDIOS}
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


def _name_keys(name: str, aliases: dict) -> set[str]:
    """What a network or studio name matches: its canonical id if it's a
    known one, and always its normalised text (so typed-in names match)."""
    key = _norm(name)
    return aliases.get(key, set()) | {key}


def _setting_keys(entries, known_ids, aliases) -> frozenset:
    keys: set[str] = set()
    for entry in entries:
        keys |= {entry} if entry in known_ids else _name_keys(entry, aliases)
    return frozenset(keys)


def _named_reason(what: str, names, include_keys, exclude_keys, aliases,
                  confirmed: bool = False) -> str | None:
    """Why a title with these network/studio names is filtered out, or None
    if it passes. No known name passes. `confirmed` means the site's own
    search already matched the include list."""
    names = [n for n in names if isinstance(n, str) and n.strip()]
    if not names or not (include_keys or exclude_keys):
        return None
    for name in names:
        if _name_keys(name, aliases) & exclude_keys:
            return f"{what} {name} is excluded"
    if include_keys and not confirmed and not any(
            _name_keys(name, aliases) & include_keys for name in names):
        return f"{what} {', '.join(names)} is not in the selected {what}s"
    return None


@dataclass(frozen=True)
class Rules:
    """Everything that can filter one kind of title (movie, TV or anime)."""
    languages: tuple[str, ...] = ()
    include_genres: frozenset = frozenset()
    exclude_genres: frozenset = frozenset()
    include_networks: tuple[str, ...] = ()
    exclude_networks: tuple[str, ...] = ()
    include_studios: tuple[str, ...] = ()
    exclude_studios: tuple[str, ...] = ()
    _keys: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self):
        self._keys.update({
            "include_networks": _setting_keys(self.include_networks, NETWORK_IDS,
                                              _NETWORK_ALIASES),
            "exclude_networks": _setting_keys(self.exclude_networks, NETWORK_IDS,
                                              _NETWORK_ALIASES),
            "include_studios": _setting_keys(self.include_studios, STUDIO_IDS,
                                             _STUDIO_ALIASES),
            "exclude_studios": _setting_keys(self.exclude_studios, STUDIO_IDS,
                                             _STUDIO_ALIASES),
        })

    @property
    def active(self) -> bool:
        return bool(self.languages or self.include_genres or self.exclude_genres
                    or self.include_networks or self.exclude_networks
                    or self.include_studios or self.exclude_studios)

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
        return _named_reason("network", [network], self._keys["include_networks"],
                             self._keys["exclude_networks"], _NETWORK_ALIASES)

    def studio_reason(self, studios, confirmed: bool = False) -> str | None:
        """Why a film from these studios is filtered out, or None if it
        passes. Any one of them matching the include list is enough."""
        return _named_reason("studio", list(studios), self._keys["include_studios"],
                             self._keys["exclude_studios"], _STUDIO_ALIASES,
                             confirmed)

    def signature(self) -> str:
        """Short fingerprint, stored with filtered titles so a change to the
        filters gets them looked at again straight away."""
        parts = [sorted(self.languages), sorted(self.include_genres),
                 sorted(self.exclude_genres), sorted(self.include_networks),
                 sorted(self.exclude_networks)]
        # Only when set, so adding studio filters didn't change every
        # existing fingerprint (and re-check every filtered title).
        if self.include_studios or self.exclude_studios:
            parts += [sorted(self.include_studios), sorted(self.exclude_studios)]
        blob = json.dumps(parts)
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
            ids = sorted({i for n in self.include_networks for i in _TMDB_NETWORK[n]})
            params["with_networks"] = "|".join(map(str, ids))
        if media_type == MOVIE and not series:
            if self.include_studios and \
                    all(n in _TMDB_COMPANY for n in self.include_studios):
                ids = sorted({i for n in self.include_studios for i in _TMDB_COMPANY[n]})
                params["with_companies"] = "|".join(map(str, ids))
            # TMDB drops a film if any of its production companies is
            # excluded, not only the first one Radarr reports: what excluding
            # a studio means. Typed-in names have no id and aren't pushed.
            ids = sorted({i for n in self.exclude_studios for i in _TMDB_COMPANY.get(n, [])})
            if ids:
                params["without_companies"] = ",".join(map(str, ids))
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
    studios = (getattr(settings, "studio_filters", None) or {}).get(kind, {})
    return Rules(
        languages=tuple(lang.lower() for lang in languages),
        include_genres=frozenset(genres.get("include", ())),
        exclude_genres=frozenset(genres.get("exclude", ())),
        include_networks=tuple(networks.get("include", ())),
        exclude_networks=tuple(networks.get("exclude", ())),
        include_studios=tuple(studios.get("include", ())),
        exclude_studios=tuple(studios.get("exclude", ())),
    )
