# Fresharr

> [!WARNING]
> **Early alpha.** Fresharr is brand new and largely untested in the wild — it
> may not work as intended, and settings or behaviour may change between
> versions without notice. Several discovery sites are scraped (they have no
> public APIs) and can break whenever those sites change. Run it with
> `DRY_RUN=true` first, watch the logs, and expect rough edges. Bug reports
> are very welcome via [issues](https://github.com/krippler/fresharr/issues).

Fresharr discovers **new and highly rated movies, TV shows & anime** from Rotten
Tomatoes, Metacritic, Letterboxd, TMDB, Trakt, AniList and MyAnimeList, and
automatically adds them to **Radarr** and **Sonarr**. Pick your sites and schedule
in the web interface, set minimum score thresholds, and let your library grow with
well-reviewed releases — no manual searching.

Built to run as a lightweight Docker container, with a ready-made **Unraid**
Community Applications template.

## The web interface

Fresharr serves a web UI on port `8383`. **All configuration lives here** —
the only things set on the container itself are the port, the `/config` path,
and `DRY_RUN`. In the UI you control:

- **Connections** — Radarr and Sonarr URLs, API keys, quality profiles and
  root folders. Once a connection works, the quality profile and root folder
  become **dropdowns populated live from that app's API** — no typing names.
  Fields save as you leave them and apply on the next run.
- **Which discovery sites are used** — enable or disable each site individually
  with a toggle, and set each site's score threshold and **minimum number of
  reviews/ratings** (on sites that report one: TMDB, Trakt, Letterboxd,
  MyAnimeList) right on its row. Sites that need an API key (TMDB, Trakt) take
  it in the same place.
- **The run schedule** — from once a day (the most frequent allowed) up to every
  2–3 days, weekly, twice a month, or monthly. The interval is a target, not an
  exact timer: each run happens at a **random time** around it (±6 hours), and
  never less than 18 hours after the previous run — so with the daily preset,
  runs land somewhere between 18 and 30 hours apart, at a different time of day
  each cycle. This randomization is built in and not configurable.
- **Original language** — separate multi-select filters for **Movies**,
  **TV shows** and **Anime**. Only titles whose original language is selected
  get added; nothing selected means all languages. Applies where the source
  reports a language (TMDB, Trakt, AniList, MyAnimeList); the scraped review
  sites don't carry language metadata, so their titles always pass.
- **Limits** — max additions per run and minimum release year.
- **Run now** — trigger a discovery pass immediately.
- Status: last/next run, what was added, and recent additions.

Everything is stored in `/config/settings.json` and takes effect immediately —
no container restart. Environment variables still work as *defaults* (handy for
docker-compose), but a value set in the UI always wins; clearing a UI field
falls back to the environment value.

## Discovery sites

### Movies & TV

| Site | Needs | What it finds |
|---|---|---|
| **Rotten Tomatoes** (default on) | nothing | Certified-fresh theatrical releases filtered by Tomatometer / audience score. |
| **Metacritic** | nothing | Recent movies & TV from the browse charts, filtered by Metascore. |
| **TMDB** | free API key ([themoviedb.org](https://www.themoviedb.org/settings/api)) | Official API: recently released, highly rated titles. Most stable source, exact ID matches. **Recommended.** |
| **Trakt** | free API app client ID ([trakt.tv](https://trakt.tv/oauth/applications)) | Trending movies & shows, filtered by Trakt rating. Exact ID matches. **Recommended.** |
| **Letterboxd** (default off) | nothing | Films popular this week, filtered by Letterboxd star rating (movies only). Letterboxd rate-limits/blocks automated requests, so this source is unreliable — TMDB is the dependable alternative. |

### Anime

| Site | Needs | What it finds |
|---|---|---|
| **AniList** | nothing | Trending anime via the official GraphQL API, filtered by AniList score. |
| **MyAnimeList** | nothing | Current season + top airing anime via the Jikan API, filtered by MAL score. |

Anime handling: series are added to Sonarr with the **anime** series type
(absolute episode numbering), anime films go to Radarr, and both the English and
romaji titles are used when matching — whichever your indexers know the show by.

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
3. Looks each title up in Radarr (movies) / Sonarr (TV), skips anything already in
   your library, and adds the rest with your chosen quality profile and root folder
   (optionally triggering a search immediately).
4. Remembers what it handled in `/config/state.json` so titles are never re-added,
   even across restarts.

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
   path and Dry Run — everything else is configured in the web UI.
2. Open the **WebUI** from the container's context menu and enter your
   Radarr/Sonarr URLs and API keys (Settings → General → API Key in each app),
   then pick your discovery sites, thresholds, languages and schedule.
3. Leave **Dry Run** on `true` for the first run and check the container log to see
   what would be added; set it to `false` when you're happy with the picks.

The container runs as `nobody:users` (99:100), matching Unraid appdata conventions.

## Configuration

**Set in the web interface** (stored in `/config/settings.json`, applied
without a restart): Radarr/Sonarr URLs, API keys, quality profiles and root
folders (picked from live dropdowns); every site's score threshold and
minimum review/rating count; TMDB API key and Trakt client ID; Rotten
Tomatoes list paths; max additions per run; minimum release year;
original-language filters for movies, TV and anime; per-site toggles; and
the run schedule.

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
| `RETRY_NOT_FOUND_DAYS` | `7` | Re-try titles that had no Radarr/Sonarr match after this many days. |
| `RT_MAX_PAGES` | `2` | Rotten Tomatoes pages fetched per list (~30 titles per page). |
| `TMDB_MIN_VOTES` | `50` | Minimum TMDB vote count (filters out obscure titles). |
| `TMDB_RELEASED_WITHIN_DAYS` | `90` | TMDB: only titles released in the last N days. |
| `TMDB_MOVIES` / `TMDB_TV` | `true` | Toggle movie/TV discovery for the TMDB site. |
| `TRAKT_LIMIT` | `40` | Trakt trending items fetched per media type. |
| `LETTERBOXD_MAX_FILMS` | `30` | Popular films examined per run (each needs one page fetch). |
| `LETTERBOXD_LIST` | `popular/this/week` | Letterboxd films list to read. |
| `RADARR_MONITORED` / `SONARR_MONITORED` | `true` | Add titles as monitored. |
| `RADARR_SEARCH_ON_ADD` / `SONARR_SEARCH_ON_ADD` | `true` | Trigger a search right after adding. |
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
