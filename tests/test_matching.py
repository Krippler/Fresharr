from fresharr.arr.base import pick_best


def test_prefers_tmdb_id():
    candidates = [
        {"title": "Dune", "year": 1984, "tmdbId": 841},
        {"title": "Dune", "year": 2021, "tmdbId": 438631},
    ]
    assert pick_best(candidates, "Dune", 1984, tmdb_id=438631)["tmdbId"] == 438631


def test_matches_title_and_year():
    candidates = [
        {"title": "Dune", "year": 1984, "tmdbId": 841},
        {"title": "Dune", "year": 2021, "tmdbId": 438631},
    ]
    assert pick_best(candidates, "Dune", 2021)["tmdbId"] == 438631


def test_year_tolerance_of_one():
    candidates = [{"title": "Festival Darling", "year": 2023}]
    assert pick_best(candidates, "Festival Darling", 2024) is not None


def test_title_normalization():
    candidates = [{"title": "Spider-Man: Across the Spider-Verse", "year": 2023}]
    assert pick_best(candidates, "Spider Man Across the Spider Verse", 2023) is not None


def test_wrong_year_rejected():
    candidates = [{"title": "Dune", "year": 1984}]
    assert pick_best(candidates, "Dune", 2021) is None


def test_no_title_match_rejected():
    candidates = [{"title": "Something Else", "year": 2024}]
    assert pick_best(candidates, "Dune", 2024) is None


def test_no_year_takes_first_title_match():
    candidates = [
        {"title": "Other", "year": 2020},
        {"title": "Dune", "year": 1984},
    ]
    assert pick_best(candidates, "Dune", None)["year"] == 1984


def test_empty_candidates():
    assert pick_best([], "Dune", 2021) is None


def test_alt_titles_match():
    candidates = [{"title": "Sousou no Frieren", "year": 2026, "tvdbId": 424536}]
    assert pick_best(candidates, "Frieren: Beyond Journey's End", 2026,
                     alt_titles=("Sousou no Frieren",)) is not None
    assert pick_best(candidates, "Frieren: Beyond Journey's End", 2026) is None
