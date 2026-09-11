from pathlib import Path

from bookrag.extract.pipeline import extract_book
from bookrag.extract.resolve import save_entities
from bookrag.ingest.chapter import Chapter
from bookrag.providers.fake_provider import FakeProvider
from bookrag.query import _MAX_STATEMENT_MATCHES, Fact, facts_as_of, format_context, select_relevant_facts
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

    assert context == (
        "Ishmael\n"
        "  What happened, in order - each line is a separate moment, not a correction of the one above:\n"
        "    [ch 0] (development) Ishmael arrived."
    )


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
        "  What happened, in order - each line is a separate moment, not a correction of the one above:\n"
        "    [ch 5] (status) hasn't gone through the Choosing Day yet\n"
        "    [ch 9] (status) has completed the Choosing Day\n"
        "  Standing description - a later line refines or supersedes an earlier one:\n"
        "    personality:\n"
        "      [ch 3] is curious and eager to please"
    )


def test_format_context_separates_occurrences_from_standing_description(tmp_path: Path) -> None:
    """The structural half of the cross-event conflation fix: a wound and a
    later, unrelated death report are both `status`, and fusing them produced
    a confidently wrong answer. They must render as two moments in one
    sequence, never as a correction, while genuinely standing properties keep
    the later-wins grouping."""
    facts = [
        Fact(book_id="b", entity_id="character-1", chapter_index=66, category="status", statement="was reported killed"),
        Fact(book_id="b", entity_id="character-1", chapter_index=34, category="status", statement="was wounded"),
        Fact(book_id="b", entity_id="character-1", chapter_index=2, category="appearance", statement="has a grey beard"),
    ]

    context = format_context(facts, root=tmp_path / "library")

    assert context == (
        "character-1\n"
        "  What happened, in order - each line is a separate moment, not a correction of the one above:\n"
        "    [ch 34] (status) was wounded\n"
        "    [ch 66] (status) was reported killed\n"
        "  Standing description - a later line refines or supersedes an earlier one:\n"
        "    appearance:\n"
        "      [ch 2] has a grey beard"
    )


def test_format_context_treats_every_nonfiction_category_as_standing(tmp_path: Path) -> None:
    """Nonfiction has no occurrence categories by design - a definition or
    claim is a standing statement, so a nonfiction book keeps the grouped,
    later-wins shape rather than growing a spurious event sequence."""
    facts = [
        Fact(book_id="b", entity_id="concept-1", chapter_index=3, category="technique", statement="pair a new habit with an old one"),
        Fact(book_id="b", entity_id="concept-1", chapter_index=1, category="definition", statement="a habit is an automatic routine"),
    ]

    context = format_context(facts, root=tmp_path / "library", content_type="nonfiction")

    assert "What happened, in order" not in context
    assert context == (
        "concept-1\n"
        "  Standing description - a later line refines or supersedes an earlier one:\n"
        "    technique:\n"
        "      [ch 3] pair a new habit with an old one\n"
        "    definition:\n"
        "      [ch 1] a habit is an automatic routine"
    )


def test_format_context_keeps_separate_entities_in_separate_blocks(tmp_path: Path) -> None:
    facts = [
        Fact(book_id="b", entity_id="character-1", chapter_index=1, category="description", statement="a young apprentice"),
        Fact(book_id="b", entity_id="character-2", chapter_index=2, category="description", statement="a grizzled ranger"),
    ]

    context = format_context(facts, root=tmp_path / "library")

    assert context == (
        "character-1\n"
        "  Standing description - a later line refines or supersedes an earlier one:\n"
        "    description:\n"
        "      [ch 1] a young apprentice"
        "\n\n"
        "character-2\n"
        "  Standing description - a later line refines or supersedes an earlier one:\n"
        "    description:\n"
        "      [ch 2] a grizzled ranger"
    )


def _seed_entities(root: Path, entities: list[dict]) -> None:
    save_entities({"entities": entities}, root)


def test_select_relevant_facts_filters_to_the_named_entity(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _seed_entities(
        root,
        [
            {"entity_id": "character-halt", "canonical_name": "Halt", "type": "character", "aliases": [], "book_ids": []},
            {"entity_id": "character-will", "canonical_name": "Will", "type": "character", "aliases": [], "book_ids": []},
        ],
    )
    facts = [
        Fact(book_id="b", entity_id="character-halt", chapter_index=0, category="appearance", statement="wears a grey cloak"),
        Fact(book_id="b", entity_id="character-will", chapter_index=0, category="status", statement="is an apprentice"),
    ]

    relevant = select_relevant_facts("What does Halt look like?", facts, root=root)

    assert [f.entity_id for f in relevant] == ["character-halt"]


def test_select_relevant_facts_matches_plural_variant_via_match_key(tmp_path: Path) -> None:
    """Real motivating case: asking about "Wargal" (singular) must still
    find facts filed under the entity actually named "Wargals" (plural) -
    the exact complaint that motivated building this at all."""
    root = tmp_path / "library"
    _seed_entities(
        root,
        [{"entity_id": "setting-wargals", "canonical_name": "Wargals", "type": "setting", "aliases": [], "book_ids": []}],
    )
    facts = [Fact(book_id="b", entity_id="setting-wargals", chapter_index=0, category="description", statement="fearsome raiders")]

    relevant = select_relevant_facts("Tell me about the Wargal", facts, root=root)

    assert [f.entity_id for f in relevant] == ["setting-wargals"]


def test_select_relevant_facts_matches_an_alias(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _seed_entities(
        root,
        [
            {
                "entity_id": "character-wargals",
                "canonical_name": "Wargals",
                "type": "character",
                "aliases": ["The Wargals"],
                "book_ids": [],
            }
        ],
    )
    facts = [Fact(book_id="b", entity_id="character-wargals", chapter_index=0, category="description", statement="fearsome raiders")]

    relevant = select_relevant_facts("What are The Wargals?", facts, root=root)

    assert [f.entity_id for f in relevant] == ["character-wargals"]


def test_select_relevant_facts_is_case_insensitive(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _seed_entities(root, [{"entity_id": "character-halt", "canonical_name": "Halt", "type": "character", "aliases": [], "book_ids": []}])
    facts = [Fact(book_id="b", entity_id="character-halt", chapter_index=0, category="appearance", statement="wears a grey cloak")]

    relevant = select_relevant_facts("what does HALT look like", facts, root=root)

    assert [f.entity_id for f in relevant] == ["character-halt"]


def test_select_relevant_facts_falls_back_to_everything_when_nothing_matches(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _seed_entities(
        root,
        [
            {"entity_id": "character-halt", "canonical_name": "Halt", "type": "character", "aliases": [], "book_ids": []},
            {"entity_id": "character-will", "canonical_name": "Will", "type": "character", "aliases": [], "book_ids": []},
        ],
    )
    facts = [
        Fact(book_id="b", entity_id="character-halt", chapter_index=0, category="appearance", statement="wears a grey cloak"),
        Fact(book_id="b", entity_id="character-will", chapter_index=0, category="status", statement="is an apprentice"),
    ]

    relevant = select_relevant_facts("What has happened so far in the story?", facts, root=root)

    assert relevant == facts


def test_select_relevant_facts_of_no_facts_is_empty(tmp_path: Path) -> None:
    assert select_relevant_facts("anything", [], root=tmp_path / "library") == []


def test_select_relevant_facts_matches_statement_text_when_no_entity_is_named(tmp_path: Path) -> None:
    """A question can name an event rather than a cataloged entity ("what
    happened at the choosing ceremony?"). Entity-name matching alone returned
    the whole book for those - measured at 2.1x the model's context window on
    a real library, i.e. silently truncated."""
    root = tmp_path / "library"
    _seed_entities(root, [{"entity_id": "character-will", "canonical_name": "Will", "type": "character", "aliases": [], "book_ids": []}])
    facts = [
        Fact(book_id="b", entity_id="character-will", chapter_index=6, category="status", statement="was nervous about the Choosing Day"),
        Fact(book_id="b", entity_id="character-will", chapter_index=2, category="development", statement="climbed the kitchen wall"),
        Fact(book_id="b", entity_id="character-will", chapter_index=3, category="development", statement="ate breakfast in the hall"),
    ]

    relevant = select_relevant_facts("What happened at the choosing ceremony?", facts, root=root)

    assert [f.chapter_index for f in relevant] == [6]


def test_statement_matching_tolerates_a_reader_phrasing_that_is_not_the_books(tmp_path: Path) -> None:
    """The reason matches are ranked rather than gated on a hit count: a reader
    says "choosing ceremony", the book says "Choosing Day". They share exactly
    one word, so requiring two shared words discarded the right answer."""
    root = tmp_path / "library"
    _seed_entities(root, [])
    facts = [
        Fact(book_id="b", entity_id="e1", chapter_index=5, category="description", statement="Choosing Day decides each ward's craft"),
        Fact(book_id="b", entity_id="e1", chapter_index=8, category="description", statement="the harvest was gathered"),
    ]

    relevant = select_relevant_facts("what happened at the choosing ceremony", facts, root=root)

    assert [f.chapter_index for f in relevant] == [5]


def test_statement_matching_ignores_words_common_across_the_book(tmp_path: Path) -> None:
    """A word appearing in most statements carries no topical signal, so it
    must not drag in the whole book - that is the failure this replaces."""
    root = tmp_path / "library"
    _seed_entities(root, [])
    facts = [
        Fact(book_id="b", entity_id="e1", chapter_index=i, category="description", statement=f"the castle stood quiet on day {i}")
        for i in range(12)
    ]

    relevant = select_relevant_facts("tell me about the castle", facts, root=root)

    assert relevant == facts  # no distinctive word -> unchanged fallback, not a partial guess


def test_statement_matching_is_capped(tmp_path: Path) -> None:
    """The cap is what actually bounds context on the fallback path. Note the
    corpus has to be large for the cap to be reachable at all: a word must
    appear often enough to beat the cap while still landing under the
    one-in-ten rarity ceiling, so exceeding 80 matches needs 800+ facts."""
    root = tmp_path / "library"
    _seed_entities(root, [])
    matching = [
        Fact(book_id="b", entity_id="e1", chapter_index=i, category="description", statement=f"a Kalkara stalked the ridge {i}")
        for i in range(90)
    ]
    filler = [
        Fact(book_id="b", entity_id="e2", chapter_index=i, category="description", statement=f"the harvest was gathered in village {i}")
        for i in range(910)
    ]

    relevant = select_relevant_facts("what happened with the Kalkara", matching + filler, root=root)

    assert len(relevant) == _MAX_STATEMENT_MATCHES
    assert all("Kalkara" in f.statement for f in relevant)
