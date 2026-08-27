# Fresharr

> [!NOTE]
> **Beta.** Functional and in active use, but still maturing — settings and
> behaviour may change between versions. Start with `DRY_RUN=true`, watch the
> logs, and report anything odd via
> [issues](https://github.com/krippler/fresharr/issues).

Fresharr discovers **new and highly rated movies, TV shows & anime** from Rotten
Tomatoes, Metacritic, Letterboxd, TMDB, Trakt, AniList and MyAnimeList, and adds
them to **Radarr** and **Sonarr** automatically. Pick your sites, thresholds and
schedule in the web interface, then let your library grow on its own.

Runs as a lightweight Docker container, with an **Unraid** Community
Applications template.

## Quick start

```yaml
services:
  fresharr:
    image: ghcr.io/krippler/fresharr:latest
    container_name: fresharr
    restart: unless-stopped
    ports:
      - "8383:8383"
    environment:
      DRY_RUN: "true"
    volumes:
      - ./config:/config
```

Open `http://<host>:8383`, add your Radarr/Sonarr connections, enable the
discovery sites you want, and hit **Run now**. Everything can also be preset with
environment variables — see
[docker-compose.example.yml](docker-compose.example.yml).

### Unraid

1. Install from Community Applications — or copy
   [`unraid/fresharr.xml`](unraid/fresharr.xml) to
   `/boot/config/plugins/dockerMan/templates-user/` and add the container via
   **Docker → Add Container**. The template asks only for the port, appdata path,
   Dry Run and Log Level.
2. Open **WebUI** from the container menu and enter your Radarr/Sonarr URLs and
   API keys (in each app: Settings → General → API Key).
3. Leave **Dry Run** on for the first run, check the log, then turn it off.

The container runs as `nobody:users` (99:100), matching Unraid appdata
conventions.

## The web interface

All configuration lives here, is stored in `/config/settings.json`, and applies
without a restart. Environment variables act as defaults; a value set in the UI
always wins, and clearing a field falls back to the environment value.

- **Connections** — URL, API key, quality profile, root folder, an optional
  **anime root folder**, and an optional **tag** applied to everything Fresharr
  adds. Profile and folder become dropdowns filled live from the app's API once
  it connects; each row shows its status (connecting / connected / failed).
- **Discovery sites** — a toggle per site plus its thresholds. Sites covering
  both movies and TV (Metacritic, TMDB, Trakt) take **separate movie and TV
  thresholds**; sites that report vote counts (TMDB, Trakt, Letterboxd,
  MyAnimeList) take a minimum for those too. API keys go here as well.
- **Schedule** — daily (the maximum frequency) through monthly. The interval is a
  target, not a timer: each run lands at a random time around it (±6h) and never
  less than 18h after the last, so Fresharr never hits a site at a predictable
  hour.
- **Original language** — separate multi-selects for movies, TV and anime; none
  selected means all languages. Titles are checked against the source *and*
  against Radarr/Sonarr's own metadata, so foreign-language titles from the
  scraped sites get caught too.
- **Limits** — max additions per run, minimum release year, the back-catalog
  toggle, and the Radarr/Sonarr request timeout.
- **Status** — last and next run, plus the 15 most recent additions labelled
  Movie / TV / Anime.

Cards drag into any arrangement you like (saved separately for the 3-, 2- and
1-column views). Settings lock while a run is in progress.

## Discovery sites

Only Rotten Tomatoes is enabled by default; turn on the rest as you like.

### Movies & TV

| Site | Needs | What it finds |
|---|---|---|
| **TMDB** | free [API key](https://www.themoviedb.org/settings/api) | Recently released, highly rated titles. **Recommended.** |
| **Trakt** | free [client ID](https://trakt.tv/oauth/applications) | Trending movies & shows by Trakt rating. **Recommended.** |
| **Rotten Tomatoes** | — | Certified-fresh theatrical releases by Tomatometer / audience score. Movies only. |
| **Metacritic** | — | Recent movies & TV from the browse charts, by Metascore. |
| **Letterboxd** | — | This week's popular films by star rating. Movies only, and Letterboxd blocks automated requests, so expect it to fail often. |

### Anime

| Site | Needs | What it finds |
|---|---|---|
| **AniList** | — | Trending anime via the official GraphQL API, by AniList score. |
| **MyAnimeList** | — | Current season + top airing anime via the Jikan API, by MAL score. |

**TMDB and Trakt are the most reliable**: official APIs with exact ID matching
and full language/vote data. Rotten Tomatoes, Metacritic and Letterboxd have no
public API, so those sources parse the sites' own pages — a layout change or
block is logged as a warning and the run continues with the other sites. Please
be considerate of them: Fresharr checks at most once a day by design.

Anime series are added to Sonarr with the **anime** series type (absolute episode
numbering) and anime films go to Radarr. Both English and romaji titles are tried
when matching. Set an **anime root folder** (e.g. `/tv/Anime`) to keep anime out
of your main library folder.

### New releases vs. back catalog

By default every site looks at what's **new or trending**, so nearly everything
found is a current release. Turn on **Include older titles (back catalog)** and
the API-backed sites switch to their highest-rated titles going back to your
**minimum release year**: TMDB searches the full range by vote count, Trakt and
MyAnimeList use their all-time lists, AniList sorts by score, and Metacritic
browses back to that year. Rotten Tomatoes and Letterboxd stay new-release only.

## How it works

On each run, Fresharr:

1. Fetches candidates from every enabled site.
2. Applies your score, year and language filters, and dedupes across sites.
3. Looks each title up in Radarr (movies) / Sonarr (TV), skips anything already
   in your library or excluded by a filter, and adds the rest with your quality
   profile, root folder and tag. Radarr searches on add by default; Sonarr
   doesn't.
4. Records what it handled in `/config/state.json` so it doesn't re-check the
   same titles every run. Titles with no match, or filtered by language, are
   retried after `RETRY_NOT_FOUND_DAYS`.

Runs happen on a background thread inside the container — **the web interface
doesn't need to be open**. If Radarr or Sonarr stops responding it's dropped
after a few consecutive failures and its titles deferred to the next run, while
the other app carries on.

## Configuration

Any UI setting can also be given as an environment variable (`RADARR_URL`,
`RT_MIN_CRITICS_SCORE`, …) to act as its default. These are env-only:

| Variable | Default | Description |
|---|---|---|
| `DRY_RUN` | `false` | Log what would be added without touching Radarr/Sonarr. |
| `RUN_ONCE` | `false` | Single pass, no web server, then exit (for external schedulers). |
| `WEB_PORT` | `8383` | Port for the web interface. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `RETRY_NOT_FOUND_DAYS` | `7` | Days before retrying a title that had no match or was language-filtered. |
| `ARR_TIMEOUT` | `300` | Seconds to allow Radarr/Sonarr to respond; large libraries can be slow. |
| `RT_MAX_PAGES` | `2` | Rotten Tomatoes pages per list (~30 titles each). |
| `TMDB_MIN_VOTES` | `50` | Minimum TMDB vote count, to skip obscure titles. |
| `TMDB_RELEASED_WITHIN_DAYS` | `90` | TMDB window for new releases; ignored in back-catalog mode. |
| `TMDB_MOVIES` / `TMDB_TV` | `true` | Toggle movie/TV discovery for TMDB. |
| `TRAKT_LIMIT` | `40` | Trakt items fetched per media type. |
| `LETTERBOXD_MAX_FILMS` | `30` | Films examined per run (one page fetch each). |
| `LETTERBOXD_LIST` | `popular/this/week` | Letterboxd list to read. |
| `RADARR_MONITORED` / `SONARR_MONITORED` | `true` | Add titles as monitored. |
| `RADARR_SEARCH_ON_ADD` | `true` | Search for a movie right after adding it. |
| `SONARR_SEARCH_ON_ADD` | `false` | Search for a series right after adding it. |
| `RADARR_MINIMUM_AVAILABILITY` | `released` | `announced`, `inCinemas` or `released`. |

## Running from source

```bash
pip install -e .[dev]
pytest                             # run the test suite
RADARR_URL=http://localhost:7878 RADARR_API_KEY=... DRY_RUN=true fresharr
# web UI on http://localhost:8383
```

## License

[GPL-3.0](LICENSE)
