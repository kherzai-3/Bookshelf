from pathlib import Path

from bookrag.ingest.chapter import Chapter
from bookrag.storage import save_book, series_reading_order


def test_standalone_book_reading_order_is_just_itself(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")

    book_id = save_book(source, [Chapter(0, "One", "text")], title="Standalone Book", root=root)

    assert series_reading_order(book_id, root) == [book_id]


def test_series_reading_order_lists_earlier_books_first(tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")

    book1 = save_book(
        source, [Chapter(0, "One", "text")], title="Book One", series_name="Saga", series_position=1, root=root
    )
    book2 = save_book(
        source, [Chapter(0, "One", "text")], title="Book Two", series_name="Saga", series_position=2, root=root
    )
    book3 = save_book(
        source, [Chapter(0, "One", "text")], title="Book Three", series_name="Saga", series_position=3, root=root
    )

    assert series_reading_order(book2, root) == [book1, book2]
    assert series_reading_order(book3, root) == [book1, book2, book3]
    assert series_reading_order(book1, root) == [book1]
