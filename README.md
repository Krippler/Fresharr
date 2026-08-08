# Fresharr

> [!NOTE]
> **Beta.** Fresharr is functional and in active use, but still maturing —
> settings or behaviour may change between versions. Several discovery sites
> are scraped (they have no public APIs) and can break whenever those sites
> change; the API-backed sources (TMDB, Trakt, AniList, MyAnimeList) are the
> most reliable. Run it with `DRY_RUN=true` first, watch the logs, and expect
> the occasional rough edge. Bug reports are very welcome via
> [issues](https://github.com/krippler/fresharr/issues).

Fresharr discovers **new and highly rated movies, TV shows & anime** from Rotten
Tomatoes, Metacritic, Letterboxd, TMDB, Trakt, AniList and MyAnimeList, and
automatically adds them to **Radarr** and **Sonarr**. Pick your sites and schedule
in the web interface, set minimum score thresholds, and let your library grow with
well-reviewed releases — no manual searching.

Built to run as a lightweight Docker container, with a ready-made **Unraid**
Community Applications template.

## The web interface

Fresharr serves a web UI on port `8383`. **All configuration lives here** — the
Unraid template only asks for the port, the `/config` path and `DRY_RUN`
(everything else is optional env-var defaults). In the UI you control:

- **Connections** — Radarr and Sonarr URLs, API keys, quality profiles, root
  folders, an optional **anime root folder** (anime is added there instead of
  the main folder), and an optional **tag** applied to everything Fresharr adds.
  Once a connection works, the folder and profile fields become **dropdowns
  populated live from that app's API** — no typing names. Each connection is a
  collapsible row showing its live status (connecting / connected / failed).
  Fields save as you leave them and apply on the next run.
- **Which discovery sites are used** — enable or disable each site individually
  with a toggle, and set its thresholds right on its row. Sites covering both
  movies and TV (Metacritic, TMDB, Trakt) have **separate thresholds for movies
  and TV**. Sites that report a vote/rating count (TMDB, Trakt, Letterboxd,
  MyAnimeList) also take a **minimum** for it. Sites that need an API key
  (TMDB, Trakt) take it in the same place.
- **The run schedule** — from once a day (the most frequent allowed) up to every
  2–3 days, weekly, twice a month, or monthly. The interval is a target, not an
  exact timer: each run happens at a **random time** around it (±6 hours), and
  never less than 18 hours after the previous run — so with the daily preset,
  runs land somewhere between 18 and 30 hours apart, at a different time of day
  each cycle. This randomization is built in and not configurable.
- **Original language** — separate multi-select dropdowns for **Movies**,
  **TV shows** and **Anime**. Only titles whose original language is selected
  get added; nothing selected means all languages. Sources that report a
  language are filtered up front, and every title is checked again against
  Radarr/Sonarr's own metadata before it is added — so titles from the scraped
  review sites (which carry no language data) are still caught.
- **Limits** — max additions per run, minimum release year, a **back catalog**
  toggle (see below), and the Radarr/Sonarr request timeout.
- **Run now** — trigger a discovery pass immediately. It stays disabled until at
  least one of Radarr/Sonarr is connected and at least one discovery site is on.
- **Status** — last/next run and what was added, plus a **Recently added** list
  (latest 15) labelled Movie / TV / Anime.

Cards can be dragged into whatever arrangement you like; the layout is saved on
the server, separately for the 3-, 2- and 1-column views. While a run is in
progress settings are locked (and shown as such) so configuration can't change
underneath it.

Everything is stored in `/config/settings.json` and takes effect immediately —
no container restart. Environment variables still work as *defaults* (handy for
docker-compose), but a value set in the UI always wins; clearing a UI field
falls back to the environment value.

## Discovery sites

### Movies & TV

| Site | Needs | What it finds |
|---|---|---|
| **Rotten Tomatoes** (default on) | nothing | Certified-fresh theatrical releases filtered by Tomatometer / audience score. Movies only. |
| **Metacritic** | nothing | Recent movies & TV from the browse charts, filtered by Metascore. |
| **TMDB** | free API key ([themoviedb.org](https://www.themoviedb.org/settings/api)) | Official API: recently released, highly rated titles. Most stable source, exact ID matches. **Recommended.** |
| **Trakt** | free API app client ID ([trakt.tv](https://trakt.tv/oauth/applications)) | Trending movies & shows, filtered by Trakt rating. Exact ID matches. **Recommended.** |
| **Letterboxd** | nothing | Films popular this week, filtered by Letterboxd star rating (movies only). Letterboxd rate-limits/blocks automated requests, so this source is unreliable — TMDB is the dependable alternative. |

Only Rotten Tomatoes is enabled by default; every other site is off until you
turn it on.

### Anime

| Site | Needs | What it finds |
|---|---|---|
| **AniList** | nothing | Trending anime via the official GraphQL API, filtered by AniList score. |
| **MyAnimeList** | nothing | Current season + top airing anime via the Jikan API, filtered by MAL score. |

Anime handling: series are added to Sonarr with the **anime** series type
(absolute episode numbering), anime films go to Radarr, and both the English and
romaji titles are used when matching — whichever your indexers know the show by.
If you set an **anime root folder** on a connection (e.g. `/tv/Anime`), anime is
added there instead of the main root folder.

### New releases vs. back catalog

By default every site looks at what's **new or trending**, so almost everything
found is a current release. Turn on **Include older titles (back catalog)** in
Limits and the API-backed sites switch to their highest-rated titles going back
to your **minimum release year** instead: TMDB searches the whole range (sorted
by vote count, so well-known films surface first), Trakt uses its all-time
popular lists, AniList sorts by score, MyAnimeList uses its all-time top lists,
and Metacritic browses back to that year. Rotten Tomatoes and Letterboxd remain
new-release only.

Rotten Tomatoes, Metacritic and Letterboxd have no public APIs, so those sources
parse the sites' own page data defensively — if a site changes its layout,
Fresharr logs a warning and carries on with the other sources. For the most
reliable results, enable **TMDB** and/or **Trakt**: they are official APIs that
also report original language and vote counts (so the language and minimum-review
filters work fully on them).

## How it works

Around the cadence you set in the web UI (randomized, minimum 18 hours between
runs), Fresharr:

1. Fetches candidate titles from every **enabled** discovery site.
2. Filters by your score/year thresholds and language selections, and dedupes
   across sites.
3. Looks each title up in Radarr (movies) / Sonarr (TV). Anything already in your
   library is skipped, anything whose original language isn't selected is skipped,
   and the rest are added with your chosen quality profile, root folder and tag
   (Radarr also triggers a search by default; Sonarr does not).
4. Remembers what it handled in `/config/state.json` (capped at 10,000 entries,
   oldest pruned) so it doesn't re-check the same titles every run. Titles that
   had no match, or were filtered by language, are re-checked after
   `RETRY_NOT_FOUND_DAYS`. Duplicates are detected from Radarr/Sonarr's own
   lookup results, so nothing is added twice even if an entry is pruned.

If Radarr or Sonarr stops responding mid-run, Fresharr stops sending to it after
a few consecutive failures and defers the rest of its titles to the next run,
rather than waiting out a timeout for every candidate. The other app keeps going.

Runs happen inside the container on a background thread — **the web interface
does not need to be open** for scheduled runs to fire.

> **Tip:** start with `DRY_RUN=true` and watch the logs. Nothing is sent to
> Radarr/Sonarr until you flip it to `false`.

## Quick start (docker compose)

```yaml
services:
  fresharr:
    image: ghcr.io/krippler/fresharr:latest
    container_name: fresharr
    restart: unless-stopped
    ports:
      - "8383:8383"
    environment:
      RADARR_URL: http://radarr:7878
      RADARR_API_KEY: your-radarr-api-key
      SONARR_URL: http://sonarr:8989
      SONARR_API_KEY: your-sonarr-api-key
      DRY_RUN: "true"
    volumes:
      - ./config:/config
```

Then open `http://<host>:8383`, pick your sites and schedule, and hit **Run now**.
See [docker-compose.example.yml](docker-compose.example.yml) for every option.

## Unraid

1. Install from Community Applications (or add the template manually:
   copy [`unraid/fresharr.xml`](unraid/fresharr.xml) to
   `/boot/config/plugins/dockerMan/templates-user/` and add the container via
   **Docker → Add Container**). The template only asks for the port, appdata
   path, Dry Run and Log Level — everything else is configured in the web UI.
2. Open the **WebUI** from the container's context menu and enter your
   Radarr/Sonarr URLs and API keys (Settings → General → API Key in each app),
   then pick your discovery sites, thresholds, languages and schedule.
3. Leave **Dry Run** on `true` for the first run and check the container log to see
   what would be added; set it to `false` when you're happy with the picks.

The container runs as `nobody:users` (99:100), matching Unraid appdata conventions.

## Configuration

**Set in the web interface** (stored in `/config/settings.json`, applied
without a restart): Radarr/Sonarr URLs, API keys, quality profiles, root
folders, anime root folders and tags (picked from live dropdowns where
applicable); every site's score thresholds — separate movie/TV values where the
site covers both — and minimum review/rating counts; TMDB API key and Trakt
client ID; Rotten Tomatoes list paths; max additions per run; minimum release
year; the back-catalog toggle; the Radarr/Sonarr timeout; original-language
filters for movies, TV and anime; per-site toggles; and the run schedule.

**Environment variables** cover runtime behaviour and advanced tuning. Any
UI-editable setting can *also* be provided as an env var (same names as before,
e.g. `RADARR_URL`, `RT_MIN_CRITICS_SCORE`) — the env value acts as the default
and the UI value overrides it.

| Variable | Default | Description |
|---|---|---|
| `DRY_RUN` | `false` | Log what would be added without touching Radarr/Sonarr. |
| `RUN_ONCE` | `false` | Single discovery pass, no web server, then exit (for external schedulers). |
| `WEB_PORT` | `8383` | Port for the web interface. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `RETRY_NOT_FOUND_DAYS` | `7` | Re-check titles that had no match, or were filtered by language, after this many days. |
| `ARR_TIMEOUT` | `300` | Seconds to allow Radarr/Sonarr to respond (large libraries can be slow). |
| `RT_MAX_PAGES` | `2` | Rotten Tomatoes pages fetched per list (~30 titles per page). |
| `TMDB_MIN_VOTES` | `50` | Minimum TMDB vote count (filters out obscure titles). |
| `TMDB_RELEASED_WITHIN_DAYS` | `90` | TMDB: only titles released in the last N days (ignored in back-catalog mode). |
| `TMDB_MOVIES` / `TMDB_TV` | `true` | Toggle movie/TV discovery for the TMDB site. |
| `TRAKT_LIMIT` | `40` | Trakt items fetched per media type. |
| `LETTERBOXD_MAX_FILMS` | `30` | Popular films examined per run (each needs one page fetch). |
| `LETTERBOXD_LIST` | `popular/this/week` | Letterboxd films list to read. |
| `RADARR_MONITORED` / `SONARR_MONITORED` | `true` | Add titles as monitored. |
| `RADARR_SEARCH_ON_ADD` | `true` | Trigger a Radarr search right after adding. |
| `SONARR_SEARCH_ON_ADD` | `false` | Trigger a Sonarr search right after adding (off so new series don't grab immediately). |
| `RADARR_MINIMUM_AVAILABILITY` | `released` | `announced`, `inCinemas` or `released`. |

## Running from source

```bash
pip install -e .[dev]
pytest                             # run the test suite
RADARR_URL=http://localhost:7878 RADARR_API_KEY=... DRY_RUN=true fresharr
# web UI now on http://localhost:8383
```

## A note on scraping

Rotten Tomatoes, Metacritic and Letterboxd have no official APIs, so those
sources parse the same data the sites' own pages load. Those pages can change or
start blocking automated requests without warning; when they do, Fresharr logs a
warning and keeps running. For fully supported data sources, use **TMDB** or
**Trakt** — official APIs that don't block. Please be considerate: Fresharr never
checks more than once a day by design, and keeps `RT_MAX_PAGES` small.

## License

[GPL-3.0](LICENSE)
