from pathlib import Path

from bookrag.eval import (
    groundedness_score,
    near_duplicate_pairs,
    run_eval,
    summarize,
    summarize_results,
)
from bookrag.ingest.chapter import Chapter
from bookrag.providers.base import ExtractedFact, ExtractionParseError
from bookrag.providers.fake_provider import FakeProvider
from bookrag.storage import save_book


class _AlwaysFailsProvider:
    # Takes known_entity_types like the real Provider protocol does, because
    # run_eval now passes it - it accumulates known entities across chapters
    # the way extract_book does, rather than sending an empty list every time.
    def extract_facts(
        self,
        chapter_text: str,
        known_entities: list[str],
        content_type: str = "fiction",
        known_entity_types: dict[str, str] | None = None,
    ) -> list[ExtractedFact]:
        raise ExtractionParseError("simulated parse failure")


def test_groundedness_score_of_a_fully_supported_statement_is_one() -> None:
    fact = ExtractedFact("Ishmael", "character", "development", "Ishmael went to sea calmly")

    assert groundedness_score("Ishmael went to sea calmly and quietly.", fact) == 1.0


def test_groundedness_score_of_an_unsupported_statement_is_low() -> None:
    fact = ExtractedFact("Ishmael", "character", "development", "Ishmael flew rockets swiftly")

    score = groundedness_score("Ishmael went to sea calmly.", fact)

    assert score < 0.5


def test_run_eval_is_read_only(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    book_id = save_book(source, [Chapter(0, "One", "Ishmael arrived.")], title="Test Novel", root=root)

    run_eval(book_id, [0], {"fake": FakeProvider()}, root=root)

    assert not (root / book_id / "facts.jsonl").exists()
    assert not (root / "entities.json").exists()


def test_run_eval_records_parse_failures(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapter = Chapter(0, "One", "Ishmael arrived.")
    book_id = save_book(source, [chapter], title="Test Novel", root=root)

    results = run_eval(book_id, [0], {"broken": _AlwaysFailsProvider()}, root=root)
    lines = summarize(results, {0: chapter})

    assert results[0].parse_ok is False
    assert any("1 parse failure(s)" in line for line in lines)


def test_summarize_reports_per_provider_fact_counts(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    book_id = save_book(
        source, [Chapter(0, "One", "Ishmael arrived. Ahab commanded.")], title="Test Novel", root=root
    )

    results = run_eval(book_id, [0], {"fake": FakeProvider()}, root=root)
    chapters = {c.index: c for c in [Chapter(0, "One", "Ishmael arrived. Ahab commanded.")]}
    lines = summarize(results, chapters)

    assert any("[fake] 2 facts" in line for line in lines)


def test_run_eval_keeps_two_models_of_one_provider_apart(tmp_path: Path) -> None:
    """The reason `providers` takes pairs rather than a dict.

    Comparing two models means two rows whose *provider* name is identical. A
    dict keyed by provider name silently keeps only the last of them, which is
    the one comparison this command exists to make.
    """
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapter = Chapter(0, "One", "Ishmael arrived. Ahab commanded.")
    book_id = save_book(source, [chapter], title="Test Novel", root=root)

    results = run_eval(
        book_id,
        [0],
        [("ollama:model-a", FakeProvider()), ("ollama:model-b", FakeProvider())],
        root=root,
    )

    assert {r.provider_name for r in results} == {"ollama:model-a", "ollama:model-b"}


def test_run_eval_accumulates_known_entities_across_chapters(tmp_path: Path) -> None:
    """Chapter 2's prompt must know what chapter 1 introduced, as a real run
    does - passing an empty list every time measures a condition no extraction
    is ever actually in."""
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapters = [Chapter(0, "One", "Ishmael arrived."), Chapter(1, "Two", "Ahab commanded.")]
    book_id = save_book(source, chapters, title="Test Novel", root=root)

    seen: list[list[str]] = []

    class _Recording:
        def extract_facts(self, chapter_text, known_entities, content_type="fiction", known_entity_types=None):
            seen.append(list(known_entities))
            return FakeProvider().extract_facts(chapter_text, known_entities, content_type)

    run_eval(book_id, [1, 0], [("rec", _Recording())], root=root)

    # Ascending chapter order regardless of how the indices were passed in,
    # because accumulation is only meaningful in reading order.
    assert seen[0] == []
    assert seen[1], "chapter 1 should have been told what chapter 0 introduced"


def test_summarize_reports_the_quality_columns(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    chapter = Chapter(0, "One", "Ishmael arrived. Ahab commanded.")
    book_id = save_book(source, [chapter], title="Test Novel", root=root)

    results = run_eval(book_id, [0], {"fake": FakeProvider()}, root=root)
    lines = summarize(results, {0: chapter})

    quality = next(line for line in lines if "distinct entities" in line)
    assert "citable" in quality
    assert "near-duplicate" in quality
    assert "ceiling" in quality


def test_near_duplicate_pairs_catches_a_rephrasing_the_exact_dedup_misses() -> None:
    """The real failure this models: two statements the pipeline's exact-match
    dedup keeps, because they are not equal strings, that say the same thing."""
    facts = [
        ExtractedFact(
            "Morgarath", "character", "status",
            "Morgarath was driven back into the Mountains of Rain and Night fifteen years ago",
        ),
        ExtractedFact(
            "Morgarath", "character", "status",
            "Morgarath was exiled into the Mountains of Rain and Night fifteen years ago",
        ),
        ExtractedFact("Halt", "character", "appearance", "Halt wore a dull grey cloak"),
    ]

    assert facts[0].statement != facts[1].statement
    assert near_duplicate_pairs(facts) == 1


def test_citation_coverage_falls_when_a_model_paraphrases_off_the_text(tmp_path: Path) -> None:
    """The column that protects citations: a statement the chapter's own words
    support is locatable, one invented around it is not."""
    chapter = Chapter(0, "One", "Halt drew his bow and loosed. The arrow took the boar in the shoulder.")

    class _Loose:
        def extract_facts(self, chapter_text, known_entities, content_type="fiction", known_entity_types=None):
            return [
                ExtractedFact("Halt", "character", "development", "Halt drew his bow and loosed"),
                ExtractedFact("Halt", "character", "personality", "Halt contemplated his distant childhood"),
            ]

    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    book_id = save_book(source, [chapter], title="Test Novel", root=root)

    results = run_eval(book_id, [0], [("loose", _Loose())], root=root)
    summary = summarize_results(results, {0: chapter})[0]

    assert summary.facts == 2
    assert summary.quoted == 1
    assert summary.citation_coverage == 0.5
