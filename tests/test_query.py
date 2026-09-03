from pathlib import Path

from bookrag.extract.pipeline import extract_book
from bookrag.ingest.chapter import Chapter
from bookrag.providers.fake_provider import FakeProvider
from bookrag.query import Fact, facts_as_of, format_context
from bookrag.storage import save_book
from tests.helpers import NARRATIVE_PADDING


def test_facts_as_of_never_returns_a_fact_past_the_given_chapter(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapters = [
        Chapter(0, "One", f"Ishmael arrived. {NARRATIVE_PADDING}"),
        Chapter(1, "Two", f"Ahab appeared. {NARRATIVE_PADDING}"),
        Chapter(2, "Three", f"Ishmael died. {NARRATIVE_PADDING}"),
    ]
    book_id = save_book(source, chapters, title="Test Novel", root=root)
    extract_book(book_id, FakeProvider(), root=root)

    facts_at_ch0 = facts_as_of(book_id, 0, root=root)
    facts_at_ch1 = facts_as_of(book_id, 1, root=root)
    facts_at_ch2 = facts_as_of(book_id, 2, root=root)

    assert all(f.chapter_index <= 0 for f in facts_at_ch0)
    assert all(f.chapter_index <= 1 for f in facts_at_ch1)
    assert {f.statement for f in facts_at_ch0} == {"Ishmael arrived."}
    assert "Ishmael died." not in {f.statement for f in facts_at_ch1}
    assert "Ishmael died." in {f.statement for f in facts_at_ch2}


def test_facts_as_of_treats_every_earlier_series_book_as_fully_in_the_past(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")

    book1 = save_book(
        source,
        [
            Chapter(0, "One", f"Ishmael set sail. {NARRATIVE_PADDING}"),
            Chapter(1, "Two", f"Queequeg joined him. {NARRATIVE_PADDING}"),
        ],
        title="Saga Book One",
        series_name="Saga",
        series_position=1,
        root=root,
    )
    extract_book(book1, FakeProvider(), root=root)

    book2 = save_book(
        source,
        [Chapter(0, "One", f"Starbuck spoke. {NARRATIVE_PADDING}")],
        title="Saga Book Two",
        series_name="Saga",
        series_position=2,
        root=root,
    )
    extract_book(book2, FakeProvider(), root=root)

    # Querying book2 chapter 0 should include ALL of book1's facts (both
    # chapters - book1 is entirely "in the past" relative to any part of
    # book2) plus only book2's own chapter 0.
    facts = facts_as_of(book2, 0, root=root)
    statements = {f.statement for f in facts}

    assert statements == {"Ishmael set sail.", "Queequeg joined him.", "Starbuck spoke."}


def test_facts_as_of_does_not_leak_a_later_book_in_the_series(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")

    book1 = save_book(
        source,
        [Chapter(0, "One", f"Ishmael set sail. {NARRATIVE_PADDING}")],
        title="Saga Book One",
        series_name="Saga",
        series_position=1,
        root=root,
    )
    extract_book(book1, FakeProvider(), root=root)

    book2 = save_book(
        source,
        [Chapter(0, "One", f"Ishmael perished. {NARRATIVE_PADDING}")],
        title="Saga Book Two",
        series_name="Saga",
        series_position=2,
        root=root,
    )
    extract_book(book2, FakeProvider(), root=root)

    facts = facts_as_of(book1, 0, root=root)
    statements = {f.statement for f in facts}

    assert statements == {"Ishmael set sail."}
    assert "Ishmael perished." not in statements


def test_format_context_resolves_entity_names_and_includes_category(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapters = [Chapter(0, "One", f"Ishmael arrived. {NARRATIVE_PADDING}")]
    book_id = save_book(source, chapters, title="Test Novel", root=root)
    extract_book(book_id, FakeProvider(), root=root)

    facts = facts_as_of(book_id, 0, root=root)
    context = format_context(facts, root=root)

    assert context == "Ishmael\n  development:\n    [ch 0] Ishmael arrived."


def test_format_context_of_no_facts_is_empty(tmp_path: Path) -> None:
    assert format_context([]) == ""


def test_format_context_groups_same_entity_facts_by_category_and_chapter(tmp_path: Path) -> None:
    facts = [
        Fact(book_id="b", entity_id="character-1", chapter_index=9, category="status", statement="has completed the Choosing Day"),
        Fact(book_id="b", entity_id="character-1", chapter_index=5, category="status", statement="hasn't gone through the Choosing Day yet"),
        Fact(book_id="b", entity_id="character-1", chapter_index=3, category="personality", statement="is curious and eager to please"),
    ]

    context = format_context(facts, root=tmp_path / "library")

    assert context == (
        "character-1\n"
        "  status:\n"
        "    [ch 5] hasn't gone through the Choosing Day yet\n"
        "    [ch 9] has completed the Choosing Day\n"
        "  personality:\n"
        "    [ch 3] is curious and eager to please"
    )


def test_format_context_keeps_separate_entities_in_separate_blocks(tmp_path: Path) -> None:
    facts = [
        Fact(book_id="b", entity_id="character-1", chapter_index=1, category="description", statement="a young apprentice"),
        Fact(book_id="b", entity_id="character-2", chapter_index=2, category="description", statement="a grizzled ranger"),
    ]

    context = format_context(facts, root=tmp_path / "library")

    assert context == (
        "character-1\n"
        "  description:\n"
        "    [ch 1] a young apprentice"
        "\n\n"
        "character-2\n"
        "  description:\n"
        "    [ch 2] a grizzled ranger"
    )
