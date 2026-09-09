"""Persist an ingested book (source file + chapters + metadata) under
data/library/<book_id>/, and maintain a series-aware index.

Chapters are always addressed as (book_id, chapter_index), never by a bare
chapter number - two books in the same series can each have a "chapter 2"
without collision, since each book gets its own directory and its own
chapters.jsonl. The `series` field on a book's metadata is purely a grouping
signal for later cross-book consistency (e.g. a character catalog spanning a
series) - it never merges two books' chapters into one numbering space.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from bookrag.ingest.chapter import Chapter


def library_root() -> Path:
    root = os.environ.get("BOOKRAG_LIBRARY_ROOT")
    return Path(root) if root else Path("data/library")


def incoming_root() -> Path:
    root = os.environ.get("BOOKRAG_INCOMING_ROOT")
    return Path(root) if root else Path("data/incoming")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "book"


def unique_book_id(title: str, root: Path) -> str:
    base = slugify(title)
    book_id = base
    n = 2
    while (root / book_id).exists():
        book_id = f"{base}-{n}"
        n += 1
    return book_id


def save_book(
    source_path: Path,
    chapters: list[Chapter],
    *,
    title: str,
    author: str | None = None,
    series_name: str | None = None,
    series_position: int | None = None,
    content_type: str = "fiction",
    root: Path | None = None,
) -> str:
    root = root or library_root()
    root.mkdir(parents=True, exist_ok=True)

    book_id = unique_book_id(title, root)
    book_dir = root / book_id
    book_dir.mkdir(parents=True)

    try:
        shutil.copy2(source_path, book_dir / f"source{source_path.suffix.lower()}")

        metadata = {
            "book_id": book_id,
            "title": title,
            "author": author,
            "series": (
                {"name": series_name, "position": series_position}
                if series_name is not None
                else None
            ),
            "content_type": content_type,
            "source_format": source_path.suffix.lstrip(".").lower(),
            "source_filename": source_path.name,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "chapter_count": len(chapters),
        }
        (book_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        with (book_dir / "chapters.jsonl").open("w", encoding="utf-8") as f:
            for chapter in chapters:
                f.write(json.dumps(asdict(chapter)) + "\n")

        _update_index(root, metadata)
    except Exception:
        # Leave no partial book_id directory behind on failure - either
        # save_book fully succeeds, or it's as if it was never called.
        shutil.rmtree(book_dir, ignore_errors=True)
        raise

    return book_id


def load_chapters(book_id: str, root: Path | None = None) -> list[Chapter]:
    root = root or library_root()
    lines = (root / book_id / "chapters.jsonl").read_text(encoding="utf-8").splitlines()
    return [Chapter(**json.loads(line)) for line in lines]


def load_metadata(book_id: str, root: Path | None = None) -> dict:
    root = root or library_root()
    return json.loads((root / book_id / "metadata.json").read_text(encoding="utf-8"))


def load_index(root: Path | None = None) -> dict:
    root = root or library_root()
    index_path = root / "index.json"
    if not index_path.exists():
        return {"books": []}
    return json.loads(index_path.read_text(encoding="utf-8"))


def series_reading_order(book_id: str, root: Path | None = None) -> list[str]:
    """Ordered book_ids leading up to and including book_id: for a standalone
    book, just [book_id]; for a series book, every earlier book in the same
    series (by series.position) followed by book_id itself. This is the one
    piece of bookkeeping both extraction (seeding known-entities context
    across a series) and spoiler-safe querying (facts_as_of) depend on."""
    root = root or library_root()
    books = {b["book_id"]: b for b in load_index(root)["books"]}
    this_book = books.get(book_id)
    if this_book is None or not this_book.get("series"):
        return [book_id]

    series_name = this_book["series"]["name"]
    position = this_book["series"]["position"]
    earlier = [
        b["book_id"]
        for b in books.values()
        if b.get("series")
        and b["series"]["name"] == series_name
        and b["series"]["position"] < position
    ]
    earlier.sort(key=lambda bid: books[bid]["series"]["position"])
    return [*earlier, book_id]


def _update_index(root: Path, metadata: dict) -> None:
    index_path = root / "index.json"
    index = {"books": []}
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))

    books = [b for b in index["books"] if b["book_id"] != metadata["book_id"]]
    books.append(
        {
            "book_id": metadata["book_id"],
            "title": metadata["title"],
            "author": metadata["author"],
            "series": metadata["series"],
        }
    )
    index["books"] = books
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")


def remove_from_index(book_id: str, root: Path | None = None) -> bool:
    """Removes book_id's entry from index.json, if present. Returns whether
    an entry was actually found and removed - used by library.remove_book to
    report a no-op distinctly from a real removal, and to let it clean up a
    stale index entry whose directory is already gone (the orphaned-index-
    entry case bookrag doctor detects)."""
    root = root or library_root()
    index = load_index(root)
    remaining = [b for b in index["books"] if b["book_id"] != book_id]
    if len(remaining) == len(index["books"]):
        return False
    index["books"] = remaining
    (root / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return True
