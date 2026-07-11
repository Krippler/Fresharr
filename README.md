# Fresharr

Fresharr discovers **new and highly rated movies & TV shows** from Rotten Tomatoes,
IMDb, TMDB and Trakt, and automatically adds them to **Radarr** and **Sonarr**.
Pick your sites and schedule in the web interface, set minimum score thresholds,
and let your library grow with well-reviewed releases — no manual searching.

Built to run as a lightweight Docker container, with a ready-made **Unraid**
Community Applications template.

## The web interface

Fresharr serves a web UI on port `8383`. This is where you control:

- **Which discovery sites are used** — enable or disable each site individually
  with a toggle. Sites that need an API key show what's missing until you provide
  it via the container's environment.
- **The run schedule** — from once a day (the most frequent allowed) up to every
  2–3 days, weekly, twice a month, or monthly. Discovery lists change slowly, so
  Fresharr deliberately won't hammer the sites more than daily.
- **Run now** — trigger a discovery pass immediately.
- Status: last/next run, what was added, and recent additions.

Schedule and site selection are stored in `/config/settings.json` and take effect
immediately — no container restart, and they're deliberately *not* environment
variables.

## Discovery sites

| Site | Needs | What it finds |
|---|---|---|
| **Rotten Tomatoes** (default on) | nothing | Browse lists (Certified Fresh in theaters / at home, Fresh TV) filtered by Tomatometer / audience score. |
| **IMDb** | nothing | Most Popular Movies & TV charts, filtered by IMDb rating. |
| **TMDB** | free API key ([themoviedb.org](https://www.themoviedb.org/settings/api)) | Official API: recently released, highly rated titles. Most stable source, exact ID matches. |
| **Trakt** | free API app client ID ([trakt.tv](https://trakt.tv/oauth/applications)) | Trending movies & shows, filtered by Trakt rating. Exact ID matches. |

Rotten Tomatoes and IMDb have no official APIs, so those sources parse the sites'
own page data defensively — if a site changes its layout, Fresharr logs a warning
and carries on with the other sources.

## How it works

On the schedule you set in the web UI, Fresharr:

1. Fetches candidate titles from every **enabled** discovery site.
2. Filters by your score/year thresholds and dedupes across sites.
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
   **Docker → Add Container**).
2. Fill in your Radarr/Sonarr URLs and API keys (Settings → General → API Key).
3. Open the **WebUI** from the container's context menu to choose your discovery
   sites and schedule.
4. Leave **Dry Run** on `true` for the first run and check the container log to see
   what would be added; set it to `false` when you're happy with the picks.

The container runs as `nobody:users` (99:100), matching Unraid appdata conventions.

## Configuration (environment variables)

Connections, credentials, and score thresholds are environment variables.
The run schedule and per-site toggles are **web UI only** (see above).

### Connections

| Variable | Default | Description |
|---|---|---|
| `RADARR_URL` | – | Radarr base URL, e.g. `http://192.168.1.100:7878`. Empty disables movies. |
| `RADARR_API_KEY` | – | Radarr API key. |
| `SONARR_URL` | – | Sonarr base URL. Empty disables TV. |
| `SONARR_API_KEY` | – | Sonarr API key. |
| `WEB_PORT` | `8383` | Port for the web interface. |

At least one of Radarr/Sonarr must be configured.

### Site thresholds

| Variable | Default | Description |
|---|---|---|
| `RT_MIN_CRITICS_SCORE` | `80` | Minimum Tomatometer score (0–100, 0 = ignore). |
| `RT_MIN_AUDIENCE_SCORE` | `0` | Minimum audience score (0–100, 0 = ignore). |
| `RT_MOVIE_LISTS` | `movies_in_theaters/critics:certified_fresh,movies_at_home/critics:certified_fresh` | Rotten Tomatoes browse paths for movies — the part of the URL after `rottentomatoes.com/browse/`. |
| `RT_TV_LISTS` | `tv_series_browse/critics:fresh` | Browse paths for TV shows. |
| `RT_MAX_PAGES` | `2` | Pages fetched per list (~30 titles per page). |
| `IMDB_MIN_RATING` | `7.0` | Minimum IMDb rating (0–10). |
| `IMDB_MOVIE_CHARTS` | `moviemeter` | IMDb chart paths for movies. |
| `IMDB_TV_CHARTS` | `tvmeter` | IMDb chart paths for TV. |
| `TMDB_API_KEY` | – | Unlocks the TMDB site in the web UI. |
| `TMDB_MIN_RATING` | `7.5` | Minimum TMDB rating (0–10). |
| `TMDB_MIN_VOTES` | `50` | Minimum number of votes (filters out obscure/unrated titles). |
| `TMDB_RELEASED_WITHIN_DAYS` | `90` | Only consider titles released in the last N days. |
| `TMDB_MOVIES` / `TMDB_TV` | `true` | Toggle movie/TV discovery for the TMDB site. |
| `TRAKT_CLIENT_ID` | – | Unlocks the Trakt site in the web UI. |
| `TRAKT_MIN_RATING` | `7.0` | Minimum Trakt rating (0–10). |
| `TRAKT_LIMIT` | `40` | Trending items fetched per media type. |
| `MIN_YEAR` | – | Ignore titles released before this year. |

### Adding behaviour

| Variable | Default | Description |
|---|---|---|
| `RADARR_QUALITY_PROFILE` | first profile | Profile name or id. |
| `RADARR_ROOT_FOLDER` | first root folder | Root folder path as configured in Radarr. |
| `RADARR_MONITORED` | `true` | Add movies as monitored. |
| `RADARR_SEARCH_ON_ADD` | `true` | Trigger a search right after adding. |
| `RADARR_MINIMUM_AVAILABILITY` | `released` | `announced`, `inCinemas` or `released`. |
| `SONARR_QUALITY_PROFILE` | first profile | Profile name or id. |
| `SONARR_ROOT_FOLDER` | first root folder | Root folder path as configured in Sonarr. |
| `SONARR_MONITORED` | `true` | Add series as monitored. |
| `SONARR_SEARCH_ON_ADD` | `true` | Search for missing episodes after adding. |

### Runtime

| Variable | Default | Description |
|---|---|---|
| `DRY_RUN` | `false` | Log what would be added without touching Radarr/Sonarr. |
| `RUN_ONCE` | `false` | Single discovery pass, no web server, then exit (for external schedulers). |
| `MAX_ITEMS_PER_RUN` | `20` | Safety cap on additions per run. |
| `RETRY_NOT_FOUND_DAYS` | `7` | Re-try titles that had no Radarr/Sonarr match after this many days. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## Running from source

```bash
pip install -e .[dev]
pytest                             # run the test suite
RADARR_URL=http://localhost:7878 RADARR_API_KEY=... DRY_RUN=true fresharr
# web UI now on http://localhost:8383
```

## A note on scraping

Rotten Tomatoes and IMDb have no official APIs, so those sources use the same
data the sites' own pages load. Those endpoints can change without warning; when
they do, Fresharr logs a warning and keeps running. For fully supported data
sources, use TMDB or Trakt. Please be considerate: Fresharr never checks more
than once a day by design, and keeps `RT_MAX_PAGES` small.

## License

[GPL-3.0](LICENSE)
