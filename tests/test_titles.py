from bookrag.titles import guess_title_author


def test_splits_title_and_author_on_by() -> None:
    title, author = guess_title_author("Finite-and-Infinite-Games-by-James-Carse")

    assert title == "Finite and Infinite Games"
    assert author == "James Carse"


def test_no_by_pattern_returns_title_only() -> None:
    title, author = guess_title_author("pg2701-images-3")

    assert title == "Pg2701 Images 3"
    assert author is None


def test_collapses_separators_and_whitespace() -> None:
    title, _author = guess_title_author("some__weird--file_name")

    assert title == "Some Weird File Name"
