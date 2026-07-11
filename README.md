# Fresharr

Fresharr discovers **new and highly rated movies & TV shows** and automatically adds
them to **Radarr** and **Sonarr**. Point it at Rotten Tomatoes' browse lists (e.g.
*Certified Fresh in theaters*), set a minimum score, and let your library grow with
well-reviewed releases — no manual searching.

Built to run as a lightweight Docker container, with a ready-made **Unraid**
Community Applications template.

## How it works

On a schedule you control — daily by default, and never more often than daily
(`RUN_INTERVAL_DAYS`: 1 = daily, 7 = weekly, 30 = monthly) — Fresharr:

1. Fetches candidate titles from the configured **sources**:
   - **rottentomatoes** (default) — scrapes Rotten Tomatoes browse lists and filters
     by Tomatometer / audience score.
   - **tmdb** (optional) — uses The Movie Database's official free API to find
     recently released, highly rated titles. More stable than scraping and gives
     exact ID matches; needs a free API key.
2. Filters by your score/year thresholds and dedupes across sources.
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
    environment:
      RADARR_URL: http://radarr:7878
      RADARR_API_KEY: your-radarr-api-key
      SONARR_URL: http://sonarr:8989
      SONARR_API_KEY: your-sonarr-api-key
      RT_MIN_CRITICS_SCORE: "80"
      DRY_RUN: "true"
    volumes:
      - ./config:/config
```

See [docker-compose.example.yml](docker-compose.example.yml) for every option.

## Unraid

1. Install from Community Applications (or add the template manually:
   copy [`unraid/fresharr.xml`](unraid/fresharr.xml) to
   `/boot/config/plugins/dockerMan/templates-user/` and add the container via
   **Docker → Add Container**).
2. Fill in your Radarr/Sonarr URLs and API keys (Settings → General → API Key).
3. Leave **Dry Run** on `true` for the first run and check the container log to see
   what would be added.
4. Set **Dry Run** to `false` when you're happy with the picks.

The container runs as `nobody:users` (99:100), matching Unraid appdata conventions.

## Configuration

Everything is configured through environment variables.

### Connections

| Variable | Default | Description |
|---|---|---|
| `RADARR_URL` | – | Radarr base URL, e.g. `http://192.168.1.100:7878`. Empty disables movies. |
| `RADARR_API_KEY` | – | Radarr API key. |
| `SONARR_URL` | – | Sonarr base URL. Empty disables TV. |
| `SONARR_API_KEY` | – | Sonarr API key. |

At least one of Radarr/Sonarr must be configured.

### Discovery

| Variable | Default | Description |
|---|---|---|
| `SOURCES` | `rottentomatoes` | Comma-separated: `rottentomatoes`, `tmdb`. |
| `RT_MIN_CRITICS_SCORE` | `80` | Minimum Tomatometer score (0–100, 0 = ignore). |
| `RT_MIN_AUDIENCE_SCORE` | `0` | Minimum audience score (0–100, 0 = ignore). |
| `RT_MOVIE_LISTS` | `movies_in_theaters/critics:certified_fresh,movies_at_home/critics:certified_fresh` | Rotten Tomatoes browse paths for movies — the part of the URL after `rottentomatoes.com/browse/`. |
| `RT_TV_LISTS` | `tv_series_browse/critics:fresh` | Browse paths for TV shows. |
| `RT_MAX_PAGES` | `2` | Pages fetched per list (~30 titles per page). |
| `TMDB_API_KEY` | – | Free key from [themoviedb.org](https://www.themoviedb.org/settings/api); required for the `tmdb` source. |
| `TMDB_MIN_RATING` | `7.5` | Minimum TMDB rating (0–10). |
| `TMDB_MIN_VOTES` | `50` | Minimum number of votes (filters out obscure/unrated titles). |
| `TMDB_RELEASED_WITHIN_DAYS` | `90` | Only consider titles released in the last N days. |
| `TMDB_MOVIES` / `TMDB_TV` | `true` | Toggle movie/TV discovery for the tmdb source. |
| `MIN_YEAR` | – | Ignore titles released before this year. |

Any Rotten Tomatoes browse URL works as a list path — browse the site, apply filters,
and copy everything after `/browse/`. Examples: `movies_at_home/critics:certified_fresh~audience:upright`,
`movies_in_theaters/sort:newest`, `tv_series_browse/critics:fresh~sort:popular`.

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
| `RUN_INTERVAL_DAYS` | `1` | Days between runs. `1` = daily (the minimum — lower values are clamped to 1), `2`/`3` = every few days, `7` = weekly, `15` = twice a month, `30` = monthly. |
| `RUN_ONCE` | `false` | Run a single discovery pass and exit (useful with external schedulers). |
| `MAX_ITEMS_PER_RUN` | `20` | Safety cap on additions per run. |
| `RETRY_NOT_FOUND_DAYS` | `7` | Re-try titles that had no Radarr/Sonarr match after this many days. |
| `STATE_FILE` | `/config/state.json` | Where the seen-titles state is stored. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## Running from source

```bash
pip install -e .[dev]
pytest                             # run the test suite
RADARR_URL=http://localhost:7878 RADARR_API_KEY=... DRY_RUN=true RUN_ONCE=true fresharr
```

## A note on Rotten Tomatoes

Rotten Tomatoes has no official API, so the `rottentomatoes` source uses the same
internal JSON endpoint the website's browse pages use. That endpoint can change
without warning; if it does, Fresharr logs a warning and keeps running (other
sources are unaffected). For a fully supported data source, use `tmdb`. Please be
considerate: keep `RT_MAX_PAGES` small and the run interval reasonable.

## License

[GPL-3.0](LICENSE)
