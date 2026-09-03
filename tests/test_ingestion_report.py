from pathlib import Path

from bookrag.cli import classify_ingestion, write_ingestion_report
from bookrag.ingest.chapter import Chapter


def test_classify_ingestion_chapter_bound_when_most_titled() -> None:
    chapters = [Chapter(0, "One", "t"), Chapter(1, "Two", "t"), Chapter(2, None, "t")]

    assert classify_ingestion(chapters) == "chapter-bound"


def test_classify_ingestion_text_bound_when_mostly_untitled() -> None:
    chapters = [Chapter(0, None, "t"), Chapter(1, None, "t"), Chapter(2, "Two", "t")]

    assert classify_ingestion(chapters) == "text-bound"


def test_classify_ingestion_text_bound_when_empty() -> None:
    assert classify_ingestion([]) == "text-bound"


def test_write_ingestion_report_includes_classification_and_reassurance_note(tmp_path: Path) -> None:
    root = tmp_path / "library"
    (root / "some-book").mkdir(parents=True)
    chapters = [Chapter(0, None, "word " * 5), Chapter(1, None, "word " * 5)]

    report_path = write_ingestion_report("some-book", chapters, root=root)

    content = report_path.read_text(encoding="utf-8")
    assert "classification: text-bound" in content
    assert "still work correctly" in content


def test_write_ingestion_report_omits_note_when_chapter_bound(tmp_path: Path) -> None:
    root = tmp_path / "library"
    (root / "some-book").mkdir(parents=True)
    chapters = [Chapter(0, "Chapter One", "word " * 5), Chapter(1, "Chapter Two", "word " * 5)]

    report_path = write_ingestion_report("some-book", chapters, root=root)

    content = report_path.read_text(encoding="utf-8")
    assert "classification: chapter-bound" in content
    assert "still work correctly" not in content
