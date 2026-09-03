from pathlib import Path

from ebooklib import epub

from bookrag.ingest.epub_loader import extract_metadata, load_chapters
from tests.helpers import build_sample_epub


def test_load_chapters_extracts_in_reading_order(tmp_path: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    chapters = load_chapters(epub_path)

    assert [c.title for c in chapters] == ["Chapter One", "Chapter Two"]
    assert [c.index for c in chapters] == [0, 1]
    assert "hero arrives" in chapters[0].text
    assert "hero leaves" in chapters[1].text


def test_load_chapters_splits_a_single_bundled_document_by_heading(tmp_path: Path) -> None:
    """Mirrors real Gutenberg-style epubs, which bundle many chapters into a
    handful of large spine files with chapter breaks marked only by an
    internal heading - not by the spine structure (see Moby-Dick test-run
    notes in context/src/bookrag/ingest/epub_loader.py.md)."""
    book = epub.EpubBook()
    book.set_identifier("bundled-id")
    book.set_title("Bundled Book")
    book.set_language("en")

    bundle = epub.EpubHtml(title="Bundle", file_name="bundle.xhtml")
    bundle.content = (
        "<html><body>"
        "<h2>Chapter One</h2><p>The hero arrives.</p>"
        "<h2>Chapter Two</h2><p>The hero leaves.</p>"
        "</body></html>"
    )
    book.add_item(bundle)
    book.toc = (bundle,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", bundle]

    epub_path = tmp_path / "bundled.epub"
    epub.write_epub(str(epub_path), book)

    chapters = load_chapters(epub_path)

    assert [c.title for c in chapters] == ["Chapter One", "Chapter Two"]
    assert [c.index for c in chapters] == [0, 1]
    assert "hero arrives" in chapters[0].text
    assert "hero leaves" in chapters[1].text


def test_load_chapters_handles_text_html_media_type(tmp_path: Path) -> None:
    """Real-world epubs sometimes declare content documents as media_type
    "text/html" instead of the spec-required "application/xhtml+xml" -
    ebooklib then leaves them as plain EpubItem (not upgraded to EpubHtml),
    whose get_type() guesses ITEM_UNKNOWN from the ".html" extension. Found
    via a real commercially-produced epub, which load_chapters silently
    returned zero chapters for before this was fixed to check media_type
    directly."""
    book = epub.EpubBook()
    book.set_identifier("html-media-type-id")
    book.set_title("HTML Media Type Book")
    book.set_language("en")

    page = epub.EpubItem(
        uid="page1",
        file_name="page1.html",
        media_type="text/html",
        content=b"<html><body><p>The hero arrives.</p></body></html>",
    )
    book.add_item(page)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", page]

    epub_path = tmp_path / "text_html.epub"
    epub.write_epub(str(epub_path), book)

    chapters = load_chapters(epub_path)

    assert len(chapters) == 1
    assert "hero arrives" in chapters[0].text


def test_extract_metadata_reads_title_and_author(tmp_path: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    metadata = extract_metadata(epub_path)

    assert metadata["title"] == "Test Book"
    assert metadata["author"] == "Test Author"
