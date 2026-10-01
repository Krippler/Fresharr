# Changelog

All notable changes are here. The format follows Keep a Changelog, and the
top section's heading is what the release workflow reads: `## [X.Y.Z] — DATE`
on `main` publishes that version, `## [Unreleased]` publishes only `edge`.

## [0.1.2] — 2026-10-01

### Changed

- **Releases come from this file.** Merging a change whose top section here is
  a version publishes that version: the Docker image tags, the `vX.Y.Z` git
  tag and a GitHub Release with these notes. `latest` is now the newest
  release; `edge` tracks `main`.
- Non-release images report the commit they were built from (e.g.
  `0.1.1-3-g2f6972d`) in the web interface and startup log, so a bug report can
  be tied to a build.

### Fixed

- **Recently added:** long titles are shortened with an ellipsis instead of
  wrapping around the timestamp. Hover for the full title.

## [0.1.1] — 2026-08-28

### Security

- **Stored API keys are no longer sent to the browser.** The web API returned
  saved Radarr/Sonarr/TMDB/Trakt keys in full. Key fields now come back empty,
  with a marker that one is saved; leave a field blank to keep the stored key.
- Saved card layouts are capped in size, so a malformed request can't grow
  `settings.json` without bound.

### Changed

- The Fresharr icon sits to the left of the title in the web interface.
- README and Unraid template rewritten to match what the code does.

## [0.1.0] — 2026-07-16

First beta.

### Added

- **Anime root folder** for Radarr and Sonarr, e.g. `/tv/Anime`, so anime
  stays out of the main library folder.
- **Tag** applied to everything Fresharr adds, set per connection.
- **Separate movie and TV score thresholds** on Metacritic, TMDB and Trakt.
- **Back-catalog mode:** the API-backed sites look for their highest-rated
  titles back to the minimum release year, not only new releases.
- Recently added labels each title Movie, TV or Anime.
- Cards can be dragged into any arrangement, saved separately for the 3-, 2-
  and 1-column views.

### Changed

- **Original-language filters are enforced with Radarr/Sonarr's own
  metadata,** so titles from sites that report no language are caught too.
- Run now unlocks once one app is connected and one site is enabled.
- Settings are locked while a run is in progress.
- Sonarr no longer searches for a series right after adding it.
- Changing the schedule updates "Next run" straight away.
- Language selection is three compact dropdowns; connection settings collapse
  to a name and status.

### Fixed

- **Runs on very large libraries no longer time out.** Duplicates are spotted
  from the lookup result instead of fetching the whole library first.
- The Radarr/Sonarr timeout is 5 minutes (`ARR_TIMEOUT`), and an app that stops
  responding is dropped for the rest of the run instead of being retried for
  every title.
- Trakt requests carry a User-Agent, which Cloudflare was blocking without.
- The state file is capped, so it can't grow without bound.
