import os

__version__ = "0.1.2"

# What this build reports itself as. Release images are stamped with their
# version; anything else with the commit it was built from (git describe,
# e.g. "0.1.1-3-g2f6972d"), so a bug report can be tied to a build.
BUILD = os.environ.get("FRESHARR_BUILD", "").strip() or __version__
