import json
from pathlib import Path

import pytest

from bookrag.ingest.chapter import Chapter
from bookrag.storage import load_metadata, save_book, slugify, unique_book_id


def test_slugify_normalizes_punctuation_and_case() -> None:
    assert slugify("The Fellowship of the Ring!") == "the-fellowship-of-the-ring"
    assert slugify("  ---  ") == "book"


def test_unique_book_id_avoids_collisions(tmp_path: Path) -> None:
    (tmp_path / "the-hobbit").mkdir()

    assert unique_book_id("The Hobbit", tmp_path) == "the-hobbit-2"


def test_save_book_writes_source_metadata_and_chapters(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("fake epub bytes", encoding="utf-8")
    chapters = [
        Chapter(index=0, title="Chapter One", text="The hero arrives."),
        Chapter(index=1, title="Chapter Two", text="The hero leaves."),
    ]

    book_id = save_book(
        source,
        chapters,
        title="The Hobbit",
        author="J.R.R. Tolkien",
        root=root,
    )

    book_dir = root / book_id
    assert (book_dir / "source.epub").read_text(encoding="utf-8") == "fake epub bytes"

    metadata = json.loads((book_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["title"] == "The Hobbit"
    assert metadata["author"] == "J.R.R. Tolkien"
    assert metadata["series"] is None
    assert metadata["chapter_count"] == 2
    assert metadata["content_type"] == "fiction"  # default when not specified

    lines = (book_dir / "chapters.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"index": 0, "title": "Chapter One", "text": "The hero arrives."}
    assert json.loads(lines[1]) == {"index": 1, "title": "Chapter Two", "text": "The hero leaves."}


def test_save_book_persists_an_explicit_content_type(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")

    book_id = save_book(
        source, [Chapter(0, "One", "text")], title="Atomic Habits", content_type="nonfiction", root=root
    )

    assert load_metadata(book_id, root=root)["content_type"] == "nonfiction"


def test_series_books_each_keep_their_own_chapter_2(tmp_path: Path) -> None:
    """Two books in the same series both have a 'chapter 2' - they must land in
    separate book directories with independent chapter numbering, and the
    index groups them by series without merging their chapters."""
    root = tmp_path / "library"
    source1 = tmp_path / "book1.epub"
    source1.write_text("book one", encoding="utf-8")
    source2 = tmp_path / "book2.epub"
    source2.write_text("book two", encoding="utf-8")

    chapters1 = [
        Chapter(index=0, title="Chapter One", text="Book 1, chapter 1."),
        Chapter(index=1, title="Chapter Two", text="Book 1, chapter 2: the twist."),
    ]
    chapters2 = [
        Chapter(index=0, title="Chapter One", text="Book 2, chapter 1."),
        Chapter(index=1, title="Chapter Two", text="Book 2, chapter 2: a different twist."),
    ]

    book_id_1 = save_book(
        source1, chapters1, title="Series Book One", series_name="The Saga", series_position=1, root=root
    )
    book_id_2 = save_book(
        source2, chapters2, title="Series Book Two", series_name="The Saga", series_position=2, root=root
    )

    assert book_id_1 != book_id_2

    ch2_book1 = json.loads((root / book_id_1 / "chapters.jsonl").read_text(encoding="utf-8").splitlines()[1])
    ch2_book2 = json.loads((root / book_id_2 / "chapters.jsonl").read_text(encoding="utf-8").splitlines()[1])
    assert ch2_book1["text"] != ch2_book2["text"]

    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    saga_books = [b for b in index["books"] if b["series"] and b["series"]["name"] == "The Saga"]
    assert {b["book_id"] for b in saga_books} == {book_id_1, book_id_2}
    assert sorted(b["series"]["position"] for b in saga_books) == [1, 2]


def test_save_book_leaves_no_partial_directory_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr("bookrag.storage._update_index", boom)

    with pytest.raises(RuntimeError):
        save_book(source, [Chapter(0, "One", "text")], title="Doomed Book", root=root)

    assert not (root / "doomed-book").exists()
