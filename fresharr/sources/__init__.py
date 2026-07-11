from ..config import Config


def build_sources(config: Config) -> list:
    from .rottentomatoes import RottenTomatoesSource
    from .tmdb import TmdbSource

    sources = []
    for name in config.sources:
        if name == "rottentomatoes":
            sources.append(RottenTomatoesSource(config))
        elif name == "tmdb":
            sources.append(TmdbSource(config))
    return sources
