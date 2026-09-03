from pathlib import Path

import pymupdf

from bookrag.ingest.pdf_loader import extract_metadata, load_chapters
from tests.helpers import build_sample_pdf


def test_load_chapters_extracts_in_reading_order(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    build_sample_pdf(pdf_path)

    chapters = load_chapters(pdf_path)

    assert [c.title for c in chapters] == ["Chapter One", "Chapter Two"]
    assert [c.index for c in chapters] == [0, 1]
    assert "hero arrives" in chapters[0].text
    assert "hero leaves" in chapters[1].text


def test_load_chapters_falls_back_to_whole_document_without_toc(tmp_path: Path) -> None:
    pdf_path = tmp_path / "no_toc.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Just some text, no bookmarks.")
    doc.save(str(pdf_path))
    doc.close()

    chapters = load_chapters(pdf_path)

    assert len(chapters) == 1
    assert chapters[0].title is None
    assert "no bookmarks" in chapters[0].text


def test_extract_metadata_reads_title_and_author(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    build_sample_pdf(pdf_path)

    metadata = extract_metadata(pdf_path)

    assert metadata["title"] == "Test PDF Book"
    assert metadata["author"] == "Test PDF Author"
