"""Shared data model for a book's per-chapter plain text, used by every loader."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chapter:
    index: int
    title: str | None
    text: str
    # The source's own page numbers for this chapter, `[first, last]`
    # inclusive, when the file carries any - a PDF's outline gives them
    # directly, and a page-scanned epub encodes them in its spine filenames
    # (`page_200.html`). `None` for an ordinary epub, which has no pagination
    # at all. Read by `bookrag.locate` to tell a reader where a fact came
    # from; nothing else depends on it, and every chapter written before this
    # field existed simply has no key.
    #
    # A list rather than a tuple because it round-trips through
    # `chapters.jsonl`: `asdict` writes a tuple as a JSON array and
    # `Chapter(**json.loads(line))` reads it back as a list, so storing a
    # tuple would make the same chapter compare unequal to itself across a
    # save/load cycle.
    pages: list[int] | None = field(default=None)
