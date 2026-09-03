"""Shared test fixtures: synthetic epub/pdf builders, reused across test modules
so each loader/CLI test doesn't hand-roll its own sample book."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from ebooklib import epub

# Padding for synthetic single-sentence "chapter" text used across
# extraction/query tests - long enough to clear pipeline.py's
# MIN_NARRATIVE_WORDS floor (20 words) without FakeProvider mistaking any of
# it for a new entity: every sentence starts with one of FakeProvider's own
# pronoun stopwords, and no other word here is capitalized.
NARRATIVE_PADDING = (
    "It was a quiet day. He said nothing more. She had already left. "
    "They walked in silence. We waited outside."
)


def build_sample_epub(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Test Book")
    book.set_language("en")
    book.add_author("Test Author")

    c1 = epub.EpubHtml(title="Chapter One", file_name="chap1.xhtml")
    c1.content = "<html><body><h1>Chapter One</h1><p>The hero arrives.</p></body></html>"
    c2 = epub.EpubHtml(title="Chapter Two", file_name="chap2.xhtml")
    c2.content = "<html><body><h1>Chapter Two</h1><p>The hero leaves.</p></body></html>"

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
        "along the narrow, winding path ahead of him.</p></body></html>"
    )
    c2 = epub.EpubHtml(title="Chapter Two", file_name="chap2.xhtml")
    c2.content = (
        "<html><body><h1>Chapter Two</h1><p>Halt quietly handed Will the "
        "silver oakleaf without a word, marking him at last as a fully "
        "fledged ranger of the kingdom.</p></body></html>"
    )

    book.add_item(c1)
    book.add_item(c2)
    book.toc = (c1, c2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2]

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
