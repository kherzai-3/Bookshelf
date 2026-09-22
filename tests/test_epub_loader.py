from pathlib import Path

from ebooklib import epub

from bookrag.ingest.epub_loader import extract_metadata, load_chapters
from tests.helpers import build_page_scanned_epub, build_sample_epub, build_toc_titled_epub


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


def test_load_chapters_does_not_leak_head_title_into_chapter_text(tmp_path: Path) -> None:
    """Real bug: a page-scanned, Internet-Archive-produced epub declares its
    spine items as media_type="text/html" (see the test above), so ebooklib
    treats them as raw-passthrough EpubItem rather than EpubHtml - the
    latter rebuilds <head> empty, masking this everywhere else, but a raw
    EpubItem keeps its original <head><title>Page N</title> intact. Before
    _split_by_headings scoped to <body>, tree.text_content() on the whole
    document leaked that invisible title text in as the literal first line
    of every such chapter's extracted text (observed: "Page 142" prefixing
    real content, across all 286 chapters of a real ingested book)."""
    book = epub.EpubBook()
    book.set_identifier("title-leak-id")
    book.set_title("Title Leak Book")
    book.set_language("en")

    page = epub.EpubItem(
        uid="page1",
        file_name="page1.html",
        media_type="text/html",
        content=b"<html><head><title>Page 142</title></head><body><p>The hero arrives.</p></body></html>",
    )
    book.add_item(page)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", page]

    epub_path = tmp_path / "title_leak.epub"
    epub.write_epub(str(epub_path), book)

    chapters = load_chapters(epub_path)

    assert len(chapters) == 1
    assert "Page 142" not in chapters[0].text
    assert "hero arrives" in chapters[0].text


def test_extract_metadata_reads_title_and_author(tmp_path: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    metadata = extract_metadata(epub_path)

    assert metadata["title"] == "Test Book"
    assert metadata["author"] == "Test Author"


def test_a_chapter_is_titled_from_the_table_of_contents_when_it_has_no_heading(tmp_path: Path) -> None:
    """The largest single locator win in the library. Ranger's Apprentice
    names all 75 of its chapters in its navigation and none in its markup,
    so before this it had 1 titled chapter and every citation into it read
    "chapter 48"."""
    epub_path = tmp_path / "toc_titled.epub"
    build_toc_titled_epub(epub_path)

    chapters = load_chapters(epub_path)

    assert [c.title for c in chapters] == ["Chapter One", "Chapter Two"]


def test_a_document_split_into_several_chapters_does_not_share_one_toc_label(tmp_path: Path) -> None:
    """A table-of-contents entry names a *document*. When one document holds
    several chapters - the Project Gutenberg shape - its own headings are the
    better labels, and stamping the single TOC entry across all of them would
    give every chapter the same name."""
    book = epub.EpubBook()
    book.set_identifier("multi-id")
    book.set_title("Multi")
    book.set_language("en")
    page = epub.EpubHtml(title="Whole Book", file_name="all.xhtml")
    page.content = "<html><body><h1>Chapter One</h1><p>First.</p><h1>Chapter Two</h1><p>Second.</p></body></html>"
    book.add_item(page)
    book.toc = (page,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", page]
    epub_path = tmp_path / "multi.epub"
    epub.write_epub(str(epub_path), book)

    chapters = load_chapters(epub_path)

    assert [c.title for c in chapters] == ["Chapter One", "Chapter Two"]


def test_a_page_scanned_epub_records_its_page_numbers(tmp_path: Path) -> None:
    """No headings, no table of contents - the filename is the only locator
    this book has."""
    epub_path = tmp_path / "scanned.epub"
    build_page_scanned_epub(epub_path, pages=4)

    chapters = load_chapters(epub_path)

    assert [c.pages for c in chapters] == [[0, 0], [1, 1], [2, 2], [3, 3]]
    assert all(c.title is None for c in chapters)


def test_an_ordinary_epub_has_no_pages(tmp_path: Path) -> None:
    """An epub has no pagination unless it encodes one, and inventing a
    number would be worse than having none."""
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    assert all(c.pages is None for c in load_chapters(epub_path))
