import json
import shutil
from pathlib import Path

import pytest

from bookrag.extract.resolve import load_entities, save_entities
from bookrag.ingest.chapter import Chapter
from bookrag.library import list_books, remove_book, run_doctor, show_book
from bookrag.storage import load_index, save_book


def _make_book(tmp_path: Path, root: Path, title: str, chapter_count: int = 3, **kwargs) -> str:
    source = tmp_path / f"{title}.epub"
    source.write_text("x", encoding="utf-8")
    chapters = [Chapter(i, f"Chapter {i}", "text") for i in range(chapter_count)]
    return save_book(source, chapters, title=title, root=root, **kwargs)


def _write_facts(root: Path, book_id: str, records: list[dict]) -> None:
    facts_path = root / book_id / "facts.jsonl"
    with facts_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def test_list_books_is_empty_for_a_fresh_library(tmp_path: Path) -> None:
    assert list_books(root=tmp_path / "library") == []


def test_list_books_reports_never_extracted(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Unextracted Book")

    (summary,) = list_books(root=root)

    assert summary.book_id == book_id
    assert summary.fact_count is None
    assert summary.chapters_extracted is None
    assert summary.partial is False
    assert summary.entity_count == 0


def test_list_books_reports_fully_extracted_even_with_zero_fact_chapters(tmp_path: Path) -> None:
    """A genuinely complete run can still have zero facts for some chapters
    (front matter, a too-short interstitial) - real observed case: Ranger's
    Apprentice has facts for 72 of 75 chapters but the run reached the end.
    Completion must be judged by how far the run reached (max chapter_index),
    not by how many chapters happen to have at least one fact."""
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Fully Extracted Book", chapter_count=5)
    save_entities({"entities": [{"entity_id": "character-aaa", "canonical_name": "Will", "type": "character", "aliases": [], "book_ids": [book_id]}]}, root)
    _write_facts(
        root, book_id,
        [
            {"entity_id": "character-aaa", "chapter_index": 1, "category": "development", "statement": "..."},
            {"entity_id": "character-aaa", "chapter_index": 4, "category": "development", "statement": "..."},
        ],
    )  # chapters 0, 2, 3 legitimately produced zero facts; chapter 4 (the last) did produce one

    summary = show_book(book_id, root=root)

    assert summary.fact_count == 2
    assert summary.chapters_extracted == 5
    assert summary.partial is False
    assert summary.entity_count == 1


def test_list_books_reports_a_genuinely_partial_extraction(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Sampled Book", chapter_count=10)
    save_entities({"entities": [{"entity_id": "character-aaa", "canonical_name": "Will", "type": "character", "aliases": [], "book_ids": [book_id]}]}, root)
    _write_facts(
        root, book_id,
        [{"entity_id": "character-aaa", "chapter_index": i, "category": "development", "statement": "..."} for i in range(3)],
    )  # only chapters 0-2 of 10 were ever attempted

    summary = show_book(book_id, root=root)

    assert summary.chapters_extracted == 3
    assert summary.partial is True


def test_list_books_reports_an_orphaned_index_entry(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Vanishing Book")
    shutil.rmtree(root / book_id)  # simulate a directory deleted outside the CLI

    (summary,) = list_books(root=root)

    assert summary.book_id == book_id
    assert summary.orphaned is True


def test_show_book_raises_for_unknown_book_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        show_book("no-such-book", root=tmp_path / "library")


def test_remove_book_deletes_directory_and_index_entry(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Doomed Book")

    result = remove_book(book_id, root=root)

    assert result.removed_directory is True
    assert result.removed_index_entry is True
    assert not (root / book_id).exists()
    assert all(b["book_id"] != book_id for b in load_index(root)["books"])


def test_remove_book_prunes_but_keeps_an_entity_shared_with_another_book(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_a = _make_book(tmp_path, root, "Series Book One")
    book_b = _make_book(tmp_path, root, "Series Book Two")
    save_entities(
        {"entities": [{"entity_id": "character-aaa", "canonical_name": "Will", "type": "character", "aliases": [], "book_ids": [book_a, book_b]}]},
        root,
    )

    result = remove_book(book_a, root=root)

    assert result.entities_pruned == 1
    assert result.entities_deleted == 0
    (entity,) = load_entities(root)["entities"]
    assert entity["book_ids"] == [book_b]


def test_remove_book_deletes_an_entity_left_with_no_books(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Standalone Book")
    save_entities(
        {"entities": [{"entity_id": "character-aaa", "canonical_name": "Will", "type": "character", "aliases": [], "book_ids": [book_id]}]},
        root,
    )

    result = remove_book(book_id, root=root)

    assert result.entities_pruned == 1
    assert result.entities_deleted == 1
    assert load_entities(root)["entities"] == []


def test_remove_book_raises_for_unknown_book_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        remove_book("no-such-book", root=tmp_path / "library")


def test_remove_book_cleans_up_an_orphaned_index_entry_with_no_directory(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Vanishing Book")
    shutil.rmtree(root / book_id)

    result = remove_book(book_id, root=root)

    assert result.removed_directory is False
    assert result.removed_index_entry is True


def test_run_doctor_reports_a_clean_library_as_clean(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _make_book(tmp_path, root, "Fine Book")

    report = run_doctor(root=root)

    assert report.orphaned_index_entries == []
    assert report.stale_entity_book_refs == []
    assert report.orphaned_entities == []


def test_run_doctor_detects_orphaned_index_entry(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Vanishing Book")
    shutil.rmtree(root / book_id)

    report = run_doctor(root=root)

    assert report.orphaned_index_entries == [book_id]
    assert (root / "index.json").exists()
    assert any(b["book_id"] == book_id for b in load_index(root)["books"])  # untouched without --fix


def test_run_doctor_detects_stale_entity_book_ref_and_orphaned_entity(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Real Book")
    save_entities(
        {
            "entities": [
                {"entity_id": "character-aaa", "canonical_name": "Ghost", "type": "character", "aliases": [], "book_ids": ["deleted-book"]},
                {"entity_id": "character-bbb", "canonical_name": "Never Mentioned", "type": "character", "aliases": [], "book_ids": [book_id]},
            ]
        },
        root,
    )
    _write_facts(root, book_id, [])  # extracted, but produced no facts for character-bbb at all

    report = run_doctor(root=root)

    assert ("character-aaa", "deleted-book") in report.stale_entity_book_refs
    assert "character-aaa" in report.orphaned_entities  # its only book doesn't exist
    assert "character-bbb" in report.orphaned_entities  # its book exists, but never actually references it


def test_run_doctor_fix_applies_all_cleanups(tmp_path: Path) -> None:
    root = tmp_path / "library"
    good_book = _make_book(tmp_path, root, "Good Book")
    gone_book = _make_book(tmp_path, root, "Gone Book")
    shutil.rmtree(root / gone_book)
    save_entities(
        {
            "entities": [
                {"entity_id": "character-aaa", "canonical_name": "Ghost", "type": "character", "aliases": [], "book_ids": ["deleted-book"]},
                {"entity_id": "character-bbb", "canonical_name": "Real", "type": "character", "aliases": [], "book_ids": [good_book, "deleted-book"]},
            ]
        },
        root,
    )
    _write_facts(root, good_book, [{"entity_id": "character-bbb", "chapter_index": 0, "category": "development", "statement": "..."}])

    report = run_doctor(root=root, fix=True)

    assert report.fixed is True
    index_book_ids = {b["book_id"] for b in load_index(root)["books"]}
    assert gone_book not in index_book_ids
    assert good_book in index_book_ids

    entities = load_entities(root)["entities"]
    entity_ids = {e["entity_id"] for e in entities}
    assert "character-aaa" not in entity_ids  # fully orphaned - deleted
    remaining = next(e for e in entities if e["entity_id"] == "character-bbb")
    assert remaining["book_ids"] == [good_book]  # stale "deleted-book" ref pruned, real one kept
