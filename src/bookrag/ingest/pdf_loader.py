"""Load .pdf files into per-chapter plain text, using the PDF's outline/TOC."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from bookrag.ingest.chapter import Chapter


def load_chapters(path: str | Path) -> list[Chapter]:
    doc = pymupdf.open(str(path))
    toc = [entry for entry in doc.get_toc() if entry[0] == 1] or doc.get_toc()

    if not toc:
        text = "".join(page.get_text() for page in doc).strip()
        return [Chapter(index=0, title=None, text=text)] if text else []

    chapters: list[Chapter] = []
    for i, (_level, title, start_page) in enumerate(toc):
        start = start_page - 1  # pymupdf pages are 0-indexed; TOC page numbers are 1-indexed
        end = toc[i + 1][2] - 1 if i + 1 < len(toc) else doc.page_count
        text = "".join(doc[p].get_text() for p in range(start, end)).strip()
        if not text:
            continue
        chapters.append(Chapter(index=len(chapters), title=title.strip() or None, text=text))
    return chapters


def extract_metadata(path: str | Path) -> dict[str, str | None]:
    doc = pymupdf.open(str(path))
    meta = doc.metadata or {}

    def clean(value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None

    return {"title": clean(meta.get("title")), "author": clean(meta.get("author"))}
