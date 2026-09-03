import json
from pathlib import Path

from bookrag.extract.pipeline import MIN_NARRATIVE_WORDS, extract_book
from bookrag.ingest.chapter import Chapter
from bookrag.providers.base import ExtractedFact, ExtractionParseError
from bookrag.providers.fake_provider import FakeProvider
from bookrag.storage import save_book
from tests.helpers import NARRATIVE_PADDING


class _FixedResponseProvider:
    """Test double: returns the same fixed list of facts for every chapter,
    regardless of content - lets a test dictate exactly which entity names
    a "provider" reports, to exercise the grounding check deterministically."""

    def __init__(self, facts: list[ExtractedFact]) -> None:
        self._facts = facts
        self.call_count = 0

    def extract_facts(self, chapter_text: str, known_entities: list[str]) -> list[ExtractedFact]:
        self.call_count += 1
        return list(self._facts)


class _FailsOnNthCall:
    """Test double: raises ExtractionParseError on one specific call
    (reproduces a real crash seen with llama3.2:3b on a tiny dedication-page
    "chapter"), succeeds normally otherwise. Chapters are processed in
    order, so the Nth call corresponds to the Nth chapter."""

    def __init__(self, failing_call_index: int) -> None:
        self._failing_call_index = failing_call_index
        self._delegate = FakeProvider()
        self._call_count = 0

    def extract_facts(self, chapter_text: str, known_entities: list[str]) -> list[ExtractedFact]:
        call_index = self._call_count
        self._call_count += 1
        if call_index == self._failing_call_index:
            raise ExtractionParseError("simulated malformed output")
        return self._delegate.extract_facts(chapter_text, known_entities)


def test_extract_book_writes_facts_and_updates_entities(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapters = [
        Chapter(0, "Chapter One", f"Ishmael went to sea. {NARRATIVE_PADDING}"),
        Chapter(1, "Chapter Two", f"Ahab commanded the ship. Ishmael watched. {NARRATIVE_PADDING}"),
    ]
    book_id = save_book(source, chapters, title="Test Novel", root=root)

    result = extract_book(book_id, FakeProvider(), root=root)

    assert result.chapter_count == 2
    assert result.fact_count == 3  # Ishmael (ch0), Ahab + Ishmael (ch1)
    assert result.new_entity_count == 2  # Ishmael, Ahab

    facts_path = root / book_id / "facts.jsonl"
    records = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines()]
    assert [r["chapter_index"] for r in records] == [0, 1, 1]

    entities = json.loads((root / "entities.json").read_text(encoding="utf-8"))
    names = {e["canonical_name"] for e in entities["entities"]}
    assert names == {"Ishmael", "Ahab"}


def test_extract_book_reports_progress_after_every_chapter(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapters = [
        Chapter(0, "One", "Ishmael went to sea."),
        Chapter(1, "Two", "Ahab commanded."),
        Chapter(2, "Three", "The whale surfaced."),
    ]
    book_id = save_book(source, chapters, title="Test Novel", root=root)

    progress_calls: list[tuple[int, int]] = []
    extract_book(book_id, FakeProvider(), root=root, on_chapter_done=lambda done, total: progress_calls.append((done, total)))

    assert progress_calls == [(1, 3), (2, 3), (3, 3)]


def test_extract_book_seeds_known_entities_from_earlier_series_books(tmp_path: Path) -> None:
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
        [Chapter(0, "One", f"Ishmael returned. Starbuck greeted him. {NARRATIVE_PADDING}")],
        title="Saga Book Two",
        series_name="Saga",
        series_position=2,
        root=root,
    )
    result = extract_book(book2, FakeProvider(), root=root)

    # Ishmael already existed from book1; only Starbuck is new in book2.
    assert result.new_entity_count == 1
    entities = json.loads((root / "entities.json").read_text(encoding="utf-8"))
    ishmael = next(e for e in entities["entities"] if e["canonical_name"] == "Ishmael")
    assert set(ishmael["book_ids"]) == {book1, book2}


def test_extract_book_rejects_a_new_entity_never_named_in_its_chapter(tmp_path: Path) -> None:
    """Regression test: extracting the real 75-chapter Ranger's Apprentice
    omnibus against llama3.2:3b attached a real line about the protagonist
    to "Arthur Penhaligon" - a character from an entirely different book
    series, whose name never appears anywhere in that chapter's text. A
    brand-new entity must be textually grounded to be accepted."""
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapters = [
        Chapter(0, "One", f"He didn't know who his mother was or why he was special. {NARRATIVE_PADDING}"),
    ]
    book_id = save_book(source, chapters, title="Test Novel", root=root)

    hallucinated = ExtractedFact(
        entity_name="Arthur Penhaligon",
        entity_type="character",
        category="development",
        statement="he didn't know who his mother was or why he was special.",
    )
    result = extract_book(book_id, _FixedResponseProvider([hallucinated]), root=root)

    assert result.fact_count == 0
    assert result.new_entity_count == 0
    assert result.ungrounded_entity_count == 1
    entities = json.loads((root / "entities.json").read_text(encoding="utf-8"))
    assert entities["entities"] == []


def test_extract_book_accepts_a_new_entity_named_in_its_chapter(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapters = [Chapter(0, "One", f"Will looked up at Halt and nodded. {NARRATIVE_PADDING}")]
    book_id = save_book(source, chapters, title="Test Novel", root=root)

    fact = ExtractedFact(
        entity_name="Will", entity_type="character", category="development", statement="Will nodded."
    )
    result = extract_book(book_id, _FixedResponseProvider([fact]), root=root)

    assert result.fact_count == 1
    assert result.new_entity_count == 1
    assert result.ungrounded_entity_count == 0


def test_extract_book_does_not_reject_an_already_known_entity_referred_to_by_pronoun(
    tmp_path: Path,
) -> None:
    """Once "Halt" is established in chapter 0, a fact naming Halt for
    chapter 1 must not be rejected just because chapter 1's text only says
    "He" - the grounding check only gates brand-new entities."""
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapters = [
        Chapter(0, "One", f"Halt walked into the clearing. {NARRATIVE_PADDING}"),
        Chapter(1, "Two", f"He sharpened his knife in silence. {NARRATIVE_PADDING}"),
    ]
    book_id = save_book(source, chapters, title="Test Novel", root=root)

    provider = _FixedResponseProvider(
        [ExtractedFact("Halt", "character", "personality", "He is a man of few words.")]
    )
    result = extract_book(book_id, provider, root=root)

    assert result.ungrounded_entity_count == 0
    assert result.fact_count == 2  # both chapters' facts about Halt accepted
    assert result.new_entity_count == 1  # Halt, resolved once, reused for chapter 1


def test_extract_book_skips_a_chapter_with_malformed_provider_output(tmp_path: Path) -> None:
    """Regression test: extract_book crashed the entire run on a single
    chapter's ExtractionParseError (found running a real 75-chapter book
    against llama3.2:3b, which crashed on chapter 1 - a tiny "For Michael"
    dedication page). It must instead skip that chapter and keep going.
    Padded with NARRATIVE_PADDING so pipeline.py's later MIN_NARRATIVE_WORDS
    floor doesn't pre-empt the provider call before this scenario runs -
    that floor is covered by its own dedicated test."""
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapters = [
        Chapter(0, "One", f"Ishmael went to sea. {NARRATIVE_PADDING}"),
        Chapter(1, "Dedication", f"For Michael. {NARRATIVE_PADDING}"),
        Chapter(2, "Two", f"Ahab commanded the ship. {NARRATIVE_PADDING}"),
    ]
    book_id = save_book(source, chapters, title="Test Novel", root=root)

    result = extract_book(book_id, _FailsOnNthCall(failing_call_index=1), root=root)

    assert result.chapter_count == 3
    assert result.parse_failure_count == 1
    assert result.new_entity_count == 2  # Ishmael, Ahab - the failed chapter contributed nothing

    facts_path = root / book_id / "facts.jsonl"
    records = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines()]
    assert [r["chapter_index"] for r in records] == [0, 2]  # chapter 1 contributed no facts

    entities = json.loads((root / "entities.json").read_text(encoding="utf-8"))
    names = {e["canonical_name"] for e in entities["entities"]}
    assert names == {"Ishmael", "Ahab"}


def test_extract_book_skips_very_short_chapters_without_calling_the_provider(tmp_path: Path) -> None:
    """Real observed cases a small local model hallucinated facts for
    instead of recognizing as non-narrative: a 2-word chapter fragment, a
    ~9-word copyright address block, a ~5-word dedication. A chapter this
    short is never actual story content, so it's skipped before the
    provider is ever called - deterministic, and doesn't depend on the
    model recognizing non-narrative content on its own."""
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    assert len("For Michael.".split()) < MIN_NARRATIVE_WORDS
    chapters = [
        Chapter(0, "Dedication", "For Michael."),
        Chapter(1, "One", f"Will looked up at Halt and nodded. {NARRATIVE_PADDING}"),
    ]
    book_id = save_book(source, chapters, title="Test Novel", root=root)
    provider = _FixedResponseProvider(
        [ExtractedFact("Will", "character", "development", "Will nodded.")]
    )

    result = extract_book(book_id, provider, root=root)

    assert result.skipped_chapter_count == 1
    assert provider.call_count == 1  # only the second, real chapter was ever passed to the provider
    assert result.fact_count == 1

    facts_path = root / book_id / "facts.jsonl"
    records = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines()]
    assert [r["chapter_index"] for r in records] == [1]
