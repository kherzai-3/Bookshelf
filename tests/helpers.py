"""Shared test fixtures: synthetic epub/pdf builders, reused across test modules
so each loader/CLI test doesn't hand-roll its own sample book."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from ebooklib import epub

from bookrag.ingest.consolidate import CONSOLIDATION_MEDIAN_WORDS_THRESHOLD

# Padding for synthetic single-sentence "chapter" text used across
# extraction/query tests - long enough to clear pipeline.py's
# MIN_NARRATIVE_WORDS floor (20 words) without FakeProvider mistaking any of
# it for a new entity: every sentence starts with one of FakeProvider's own
# pronoun stopwords, and no other word here is capitalized.
NARRATIVE_PADDING = (
    "It was a quiet day. He said nothing more. She had already left. "
    "They walked in silence. We waited outside."
)


def _bulk_filler(min_words: int) -> str:
    """Same proper-noun-free, FakeProvider-safe padding as NARRATIVE_PADDING,
    repeated until it clears min_words - used to keep a fixture's two
    "chapters" each safely above CONSOLIDATION_MEDIAN_WORDS_THRESHOLD, so
    ingest.consolidate doesn't merge them into one for tests that assume
    two distinct chapters and have nothing to do with consolidation itself
    (that's build_fragmented_epub's job)."""
    words = (NARRATIVE_PADDING + " ").split()
    repeated = words * (min_words // len(words) + 1)
    return " ".join(repeated[:min_words])


# Comfortably above CONSOLIDATION_MEDIAN_WORDS_THRESHOLD so build_sample_epub/
# build_narrative_epub's two "chapters" are never merged by ingest.consolidate.
_UNCONSOLIDATED_CHAPTER_WORDS = CONSOLIDATION_MEDIAN_WORDS_THRESHOLD + 100


def build_sample_epub(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Test Book")
    book.set_language("en")
    book.add_author("Test Author")

    c1 = epub.EpubHtml(title="Chapter One", file_name="chap1.xhtml")
    c1.content = f"<html><body><h1>Chapter One</h1><p>The hero arrives. {_bulk_filler(_UNCONSOLIDATED_CHAPTER_WORDS)}</p></body></html>"
    c2 = epub.EpubHtml(title="Chapter Two", file_name="chap2.xhtml")
    c2.content = f"<html><body><h1>Chapter Two</h1><p>The hero leaves. {_bulk_filler(_UNCONSOLIDATED_CHAPTER_WORDS)}</p></body></html>"

    book.add_item(c1)
    book.add_item(c2)
    book.toc = (c1, c2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2]

    epub.write_epub(str(path), book)


def build_narrative_epub(path: Path) -> None:
    """Like build_sample_epub, but with chapter paragraphs long enough to
    clear pipeline.py's MIN_NARRATIVE_WORDS floor - for tests that need
    extraction to actually run against a chapter's text, not just ingestion."""
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Test Book")
    book.set_language("en")
    book.add_author("Test Author")

    c1 = epub.EpubHtml(title="Chapter One", file_name="chap1.xhtml")
    c1.content = (
        "<html><body><h1>Chapter One</h1><p>Will walked slowly through the "
        "quiet forest at dawn, listening carefully for any sign of danger "
        f"along the narrow, winding path ahead of him. {_bulk_filler(_UNCONSOLIDATED_CHAPTER_WORDS)}"
        "</p></body></html>"
    )
    c2 = epub.EpubHtml(title="Chapter Two", file_name="chap2.xhtml")
    c2.content = (
        "<html><body><h1>Chapter Two</h1><p>Halt quietly handed Will the "
        "silver oakleaf without a word, marking him at last as a fully "
        f"fledged ranger of the kingdom. {_bulk_filler(_UNCONSOLIDATED_CHAPTER_WORDS)}"
        "</p></body></html>"
    )

    book.add_item(c1)
    book.add_item(c2)
    book.toc = (c1, c2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2]

    epub.write_epub(str(path), book)


def build_fragmented_epub(path: Path, fragment_count: int = 40, words_per_fragment: int = 100) -> None:
    """A page-scanned-style epub: many small, untitled spine documents with
    no heading markup at all - mirrors a real Internet-Archive-produced
    book (one physical page per spine file) that needs
    ingest.consolidate.consolidate_fragments to be extractable well."""
    book = epub.EpubBook()
    book.set_identifier("fragmented-id")
    book.set_title("Fragmented Book")
    book.set_language("en")
    book.add_author("Fragmented Author")

    items = []
    for i in range(fragment_count):
        page = epub.EpubHtml(file_name=f"page{i}.xhtml")
        words = " ".join(f"word{i}-{w}" for w in range(words_per_fragment))
        page.content = f"<html><body><p>{words}</p></body></html>"
        book.add_item(page)
        items.append(page)

    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]

    epub.write_epub(str(path), book)


def build_sample_pdf(path: Path) -> None:
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Chapter One\nThe hero arrives.")
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Chapter Two\nThe hero leaves.")
    doc.set_toc([[1, "Chapter One", 1], [1, "Chapter Two", 2]])
    doc.set_metadata({"title": "Test PDF Book", "author": "Test PDF Author"})
    doc.save(str(path))
    doc.close()
