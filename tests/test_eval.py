from pathlib import Path

from bookrag.eval import groundedness_score, run_eval, summarize
from bookrag.ingest.chapter import Chapter
from bookrag.providers.base import ExtractedFact, ExtractionParseError
from bookrag.providers.fake_provider import FakeProvider
from bookrag.storage import save_book


class _AlwaysFailsProvider:
    def extract_facts(
        self, chapter_text: str, known_entities: list[str], content_type: str = "fiction"
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
