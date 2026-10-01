# Releases and images

## Tags

| | |
| --- | --- |
| `ghcr.io/krippler/fresharr:latest` | the newest release |
| `ghcr.io/krippler/fresharr:edge` | tracks `main`; may break |
| `ghcr.io/krippler/fresharr:0.1.2` | a specific release |
| `ghcr.io/krippler/fresharr:0.1` | the newest release in that series |

`linux/amd64` and `linux/arm64`.

## Cutting a release

Changes collect under `## [Unreleased]` at the top of
[CHANGELOG.md](CHANGELOG.md). To release them, in one commit:

1. Rename that heading to `## [X.Y.Z] — YYYY-MM-DD`.
2. Set `__version__ = "X.Y.Z"` in `fresharr/__init__.py`.

Merge it to `main`. The workflow in `.github/workflows/docker.yml` reads the top
heading, and because no `vX.Y.Z` tag exists yet it:

- publishes the image as `X.Y.Z`, `X.Y`, `latest` and `edge`,
- creates the `vX.Y.Z` git tag,
- creates the GitHub Release, with that changelog section as its notes.

If the changelog and `__version__` disagree, the build fails before anything is
published. Merges whose top section is `[Unreleased]` publish only `edge`.

The next change after a release starts a new `## [Unreleased]` section above
it. Pushing a `vX.Y.Z` tag by hand still works and does the same, minus `edge`.

## Build stamp

Every image is stamped with what it is, shown in the web interface header and
the startup log: the version on a release, otherwise the commit it was built
from, e.g. `0.1.1-3-g2f6972d` (three commits after 0.1.1).
