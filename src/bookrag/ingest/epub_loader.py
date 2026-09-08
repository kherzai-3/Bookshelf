"""Load .epub files into per-chapter plain text, in reading order."""

from __future__ import annotations

from pathlib import Path

import lxml.html
from ebooklib import epub

from bookrag.ingest.chapter import Chapter

# The EPUB spec requires "application/xhtml+xml", but real-world files (seen
# in practice: a commercially-produced epub) sometimes declare "text/html"
# instead. ebooklib only upgrades an item to EpubHtml - whose get_type()
# always reports ITEM_DOCUMENT - for the spec media type; anything else
# falls back to plain EpubItem, whose get_type() guesses from the file
# extension and doesn't recognize ".html" at all, silently excluding every
# page. Checking media_type directly is robust to both.
_DOCUMENT_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}


def load_chapters(path: str | Path) -> list[Chapter]:
    book = epub.read_epub(str(path))
    chapters: list[Chapter] = []
    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.media_type not in _DOCUMENT_MEDIA_TYPES:
            continue
        if isinstance(item, epub.EpubNav):
            continue
        tree = lxml.html.fromstring(item.get_content())
        for title, text in _split_by_headings(tree):
            if not text:
                continue
            chapters.append(Chapter(index=len(chapters), title=title, text=text))
    return chapters


def _split_by_headings(tree: lxml.html.HtmlElement) -> list[tuple[str | None, str]]:
    """Split a spine document's content at h1/h2/h3 headings when it has more
    than one - some epub generators (e.g. Project Gutenberg) bundle many real
    chapters into few spine files, with actual chapter breaks marked only by
    an internal heading, not by the spine structure. A document with 0 or 1
    heading is returned whole, unchanged from the pre-split behavior.

    Scoped to <body> (real, observed bug otherwise): a spine item that's a
    raw-passthrough EpubItem rather than ebooklib's EpubHtml (real case: an
    Internet-Archive-produced, page-scanned epub whose items declare
    media_type="text/html") keeps its original <head><title> intact, and
    tree.text_content() on the whole document would leak that invisible
    title text ("Page 142") in as the first line of the extracted chapter.
    ebooklib's EpubHtml rebuilds <head> empty, which is why this was never
    visible before. The xpath below must stay relative (".//h1", not
    "//h1") - lxml's "//" is absolute from the document root regardless of
    which element .xpath() is called on, so switching `tree` to the <body>
    element alone would silently do nothing without this too."""
    body = tree.find(".//body")
    if body is not None:
        tree = body
    headings = tree.xpath(".//h1 | .//h2 | .//h3")
    if len(headings) <= 1:
        return [(_extract_title(tree), tree.text_content().strip())]

    # Wrapped in a Private Use Area character (not a plain NUL byte, which
    # lxml rejects as invalid XML text) so it can't collide with real content.
    sentinel = "CHAPTER-BREAK"
    for heading in headings:
        marker = tree.makeelement("span")
        marker.text = sentinel
        heading.addprevious(marker)

    parts = tree.text_content().split(sentinel)
    segments: list[tuple[str | None, str]] = []
    if parts[0].strip():
        segments.append((None, parts[0].strip()))
    for heading, part in zip(headings, parts[1:]):
        segments.append((heading.text_content().strip() or None, part.strip()))
    return segments


def extract_metadata(path: str | Path) -> dict[str, str | None]:
    book = epub.read_epub(str(path))

    def first(namespace: str, name: str) -> str | None:
        values = book.get_metadata(namespace, name)
        return values[0][0] if values else None

    return {"title": first("DC", "title"), "author": first("DC", "creator")}


def _extract_title(tree: lxml.html.HtmlElement) -> str | None:
    for tag in ("h1", "h2", "h3"):
        heading = tree.find(f".//{tag}")
        if heading is not None and heading.text_content().strip():
            return heading.text_content().strip()
    return None
