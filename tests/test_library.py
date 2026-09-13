import json
import shutil
from pathlib import Path

import pytest

from bookrag.extract.resolve import load_entities, save_entities
from bookrag.ingest.chapter import Chapter
from bookrag.library import (
    detect_cross_book_entities,
    detect_duplicate_entities,
    list_books,
    merge_entities,
    remove_book,
    run_doctor,
    show_book,
    split_cross_book_entity,
)
from bookrag.storage import load_index, save_book
from tests.helpers import NARRATIVE_PADDING


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


def test_detect_duplicate_entities_finds_a_real_shaped_cluster(tmp_path: Path) -> None:
    """Mirrors the real confirmed bug: one creature ("Wargal(s)") split
    across 2 name spellings and multiple entity_types because resolution
    is type-scoped and only exact-matches (before match_key normalization).
    Detection deliberately ignores type - that's the whole point, it's
    meant to surface exactly this kind of cross-type fragmentation."""
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Fantasy Book")
    save_entities(
        {
            "entities": [
                {"entity_id": "character-a", "canonical_name": "Wargals", "type": "character", "aliases": [], "book_ids": [book_id]},
                {"entity_id": "setting-b", "canonical_name": "Wargals", "type": "setting", "aliases": [], "book_ids": [book_id]},
                {"entity_id": "theme-c", "canonical_name": "The Wargals", "type": "theme", "aliases": [], "book_ids": [book_id]},
                {"entity_id": "character-d", "canonical_name": "Halt", "type": "character", "aliases": [], "book_ids": [book_id]},
            ]
        },
        root,
    )
    _write_facts(
        root,
        book_id,
        [
            {"entity_id": "character-a", "chapter_index": 0, "category": "development", "statement": "..."},
            {"entity_id": "setting-b", "chapter_index": 1, "category": "description", "statement": "..."},
            {"entity_id": "setting-b", "chapter_index": 2, "category": "description", "statement": "..."},
        ],
    )

    clusters = detect_duplicate_entities(root=root)

    assert len(clusters) == 1  # Halt is unique, not clustered with anything
    cluster_ids = {e.entity_id for e in clusters[0]}
    assert cluster_ids == {"character-a", "setting-b", "theme-c"}
    fact_counts = {e.entity_id: e.fact_count for e in clusters[0]}
    assert fact_counts == {"character-a": 1, "setting-b": 2, "theme-c": 0}


def test_detect_duplicate_entities_no_false_positive_on_different_names(tmp_path: Path) -> None:
    root = tmp_path / "library"
    save_entities(
        {
            "entities": [
                {"entity_id": "character-a", "canonical_name": "Will", "type": "character", "aliases": [], "book_ids": []},
                {"entity_id": "character-b", "canonical_name": "Halt", "type": "character", "aliases": [], "book_ids": []},
            ]
        },
        root,
    )

    assert detect_duplicate_entities(root=root) == []


def test_run_doctor_reports_duplicates_but_fix_does_not_merge_them(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Fantasy Book")
    save_entities(
        {
            "entities": [
                {"entity_id": "character-a", "canonical_name": "Wargals", "type": "character", "aliases": [], "book_ids": [book_id]},
                {"entity_id": "setting-b", "canonical_name": "Wargals", "type": "setting", "aliases": [], "book_ids": [book_id]},
            ]
        },
        root,
    )
    _write_facts(
        root,
        book_id,
        [
            {"entity_id": "character-a", "chapter_index": 0, "category": "development", "statement": "..."},
            {"entity_id": "setting-b", "chapter_index": 1, "category": "description", "statement": "..."},
        ],
    )

    report = run_doctor(root=root, fix=True)

    assert len(report.duplicate_entity_groups) == 1
    entity_ids = {e["entity_id"] for e in load_entities(root)["entities"]}
    assert entity_ids == {"character-a", "setting-b"}  # untouched by --fix


def test_merge_entities_rewrites_facts_and_populates_aliases(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Fantasy Book")
    save_entities(
        {
            "entities": [
                {"entity_id": "setting-dominant", "canonical_name": "Wargals", "type": "character", "aliases": [], "book_ids": [book_id]},
                {"entity_id": "theme-straggler", "canonical_name": "The Wargals", "type": "character", "aliases": [], "book_ids": [book_id]},
            ]
        },
        root,
    )
    _write_facts(
        root,
        book_id,
        [
            {"entity_id": "setting-dominant", "chapter_index": 0, "category": "description", "statement": "a"},
            {"entity_id": "setting-dominant", "chapter_index": 1, "category": "description", "statement": "b"},
            {"entity_id": "theme-straggler", "chapter_index": 2, "category": "description", "statement": "c"},
        ],
    )

    result = merge_entities(["setting-dominant", "theme-straggler"], root=root)

    assert result.kept_entity_id == "setting-dominant"  # defaulted to the entity with more facts
    assert result.merged_entity_ids == ["theme-straggler"]
    assert result.facts_rewritten == 1

    facts = [json.loads(line) for line in (root / book_id / "facts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {f["entity_id"] for f in facts} == {"setting-dominant"}  # all 3 facts now point at the kept entity

    (remaining,) = load_entities(root)["entities"]
    assert remaining["entity_id"] == "setting-dominant"
    assert remaining["aliases"] == ["The Wargals"]  # the dead alias field, finally populated


def test_merge_entities_unions_book_ids_across_multiple_books(tmp_path: Path) -> None:
    root = tmp_path / "library"
    book_a = _make_book(tmp_path, root, "Book A")
    book_b = _make_book(tmp_path, root, "Book B")
    save_entities(
        {
            "entities": [
                {"entity_id": "character-a", "canonical_name": "Wargal", "type": "character", "aliases": [], "book_ids": [book_a]},
                {"entity_id": "character-b", "canonical_name": "Wargals", "type": "character", "aliases": [], "book_ids": [book_b]},
            ]
        },
        root,
    )

    result = merge_entities(["character-a", "character-b"], keep="character-a", root=root)

    assert result.kept_entity_id == "character-a"
    (remaining,) = load_entities(root)["entities"]
    assert sorted(remaining["book_ids"]) == sorted([book_a, book_b])


def test_merge_entities_raises_for_fewer_than_two_valid_ids(tmp_path: Path) -> None:
    root = tmp_path / "library"
    save_entities(
        {"entities": [{"entity_id": "character-a", "canonical_name": "Will", "type": "character", "aliases": [], "book_ids": []}]},
        root,
    )

    with pytest.raises(ValueError):
        merge_entities(["character-a", "no-such-entity"], root=root)


def test_merge_entities_raises_when_keep_is_not_in_the_group(tmp_path: Path) -> None:
    root = tmp_path / "library"
    save_entities(
        {
            "entities": [
                {"entity_id": "character-a", "canonical_name": "Wargal", "type": "character", "aliases": [], "book_ids": []},
                {"entity_id": "character-b", "canonical_name": "Wargals", "type": "character", "aliases": [], "book_ids": []},
            ]
        },
        root,
    )

    with pytest.raises(ValueError):
        merge_entities(["character-a", "character-b"], keep="character-c", root=root)


def test_run_doctor_reports_a_fact_pointing_at_an_unregistered_entity(tmp_path: Path) -> None:
    """The inverse of the orphaned-entity check, and the damaging direction.
    A real run killed mid-chapter left 38 facts (chapters 4-10 of a real book)
    referencing entity_ids that were never written to entities.json, because
    facts flushed per chapter while the registry only saved at the end. Those
    facts render as a raw id and are unreachable by entity-name retrieval."""
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Fantasy Book")
    save_entities(
        {"entities": [{"entity_id": "character-known", "canonical_name": "Halt", "type": "character", "aliases": [], "book_ids": [book_id]}]},
        root,
    )
    _write_facts(
        root,
        book_id,
        [
            {"entity_id": "character-known", "chapter_index": 0, "category": "appearance", "statement": "wears a grey cloak"},
            {"entity_id": "character-lost", "chapter_index": 4, "category": "appearance", "statement": "Lady Pauline was slim and grey-haired"},
        ],
    )

    report = run_doctor(root=root)

    assert report.unnamed_fact_refs == [(book_id, "character-lost")]


def test_doctor_fix_never_deletes_facts_with_an_unregistered_entity(tmp_path: Path) -> None:
    """--fix must leave these alone. The name is unrecoverable (a fact stores
    only the entity_id), so deleting is destroying real content to satisfy a
    consistency check - re-extraction is the only honest repair."""
    root = tmp_path / "library"
    book_id = _make_book(tmp_path, root, "Fantasy Book")
    save_entities({"entities": []}, root)
    _write_facts(
        root,
        book_id,
        [{"entity_id": "character-lost", "chapter_index": 4, "category": "appearance", "statement": "Lady Pauline was slim"}],
    )

    report = run_doctor(root=root, fix=True)

    assert report.unnamed_fact_refs == [(book_id, "character-lost")]
    surviving = (root / book_id / "facts.jsonl").read_text(encoding="utf-8")
    assert "Lady Pauline" in surviving


def _book_with_entity(root: Path, tmp_path: Path, title: str, entity_id: str, n_facts: int,
                       series_name: str | None = None, series_position: int | None = None) -> str:
    source = tmp_path / f"{title}.epub"
    source.write_text("x", encoding="utf-8")
    book_id = save_book(
        source,
        [Chapter(0, "One", f"A chapter about someone. {NARRATIVE_PADDING}")],
        title=title,
        series_name=series_name,
        series_position=series_position,
        root=root,
    )
    facts = [
        json.dumps({"entity_id": entity_id, "chapter_index": 0, "category": "description",
                    "statement": f"fact {i}", "when": "present"})
        for i in range(n_facts)
    ]
    (root / book_id / "facts.jsonl").write_text("\n".join(facts) + "\n", encoding="utf-8")
    return book_id


def test_doctor_detects_an_entity_shared_by_unrelated_books(tmp_path: Path) -> None:
    root = tmp_path / "library"
    shared = "character-abc12345"
    book1 = _book_with_entity(root, tmp_path, "A Sea Story", shared, 3)
    book2 = _book_with_entity(root, tmp_path, "An Unrelated Novel", shared, 1)
    save_entities(
        {"entities": [{"entity_id": shared, "canonical_name": "Michael", "type": "character",
                       "aliases": [], "book_ids": [book1, book2]}]},
        root,
    )

    found = detect_cross_book_entities(root)

    assert len(found) == 1
    assert found[0].canonical_name == "Michael"
    assert found[0].facts_per_book == {book1: 3, book2: 1}


def test_doctor_does_not_flag_an_entity_shared_within_one_series(tmp_path: Path) -> None:
    """Sharing identity across a series is the feature, not the bug - book 2
    must not re-introduce a character book 1 established."""
    root = tmp_path / "library"
    shared = "character-abc12345"
    book1 = _book_with_entity(root, tmp_path, "Saga One", shared, 2, series_name="Saga", series_position=1)
    book2 = _book_with_entity(root, tmp_path, "Saga Two", shared, 2, series_name="Saga", series_position=2)
    save_entities(
        {"entities": [{"entity_id": shared, "canonical_name": "Halt", "type": "character",
                       "aliases": [], "book_ids": [book1, book2]}]},
        root,
    )

    assert detect_cross_book_entities(root) == []


def test_split_gives_each_book_its_own_entity_and_rewrites_its_facts(tmp_path: Path) -> None:
    root = tmp_path / "library"
    shared = "character-abc12345"
    book1 = _book_with_entity(root, tmp_path, "A Sea Story", shared, 3)
    book2 = _book_with_entity(root, tmp_path, "An Unrelated Novel", shared, 1)
    save_entities(
        {"entities": [{"entity_id": shared, "canonical_name": "Michael", "type": "character",
                       "aliases": [], "book_ids": [book1, book2]}]},
        root,
    )

    result = split_cross_book_entity(shared, root)

    assert len(result.new_entity_ids) == 1
    assert result.facts_rewritten == 1  # only the smaller book's facts move
    entities = load_entities(root)["entities"]
    assert len(entities) == 2
    assert {e["canonical_name"] for e in entities} == {"Michael"}
    # The book with the most facts keeps the original id, so fewest records move.
    by_book = {e["book_ids"][0]: e["entity_id"] for e in entities}
    assert by_book[book1] == shared
    assert by_book[book2] != shared
    # Every fact now points at its own book's entity - nothing left dangling.
    for book_id, expected in by_book.items():
        records = [
            json.loads(line)
            for line in (root / book_id / "facts.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert records and all(r["entity_id"] == expected for r in records)


def test_split_drops_a_book_reference_with_no_facts_behind_it(tmp_path: Path) -> None:
    """`extract --restart` truncates facts.jsonl but leaves entities.json
    alone, so a book_id recorded by the pre-restart run can outlive every
    fact that justified it. Observed in the real library: a "Michael" whose
    registry row claimed Ranger's Apprentice while zero facts there
    referenced it. That is a stale reference, not a second character, so it
    is dropped rather than given an entity of its own."""
    root = tmp_path / "library"
    shared = "character-abc12345"
    book1 = _book_with_entity(root, tmp_path, "A Sea Story", shared, 2)
    book2 = _book_with_entity(root, tmp_path, "An Unrelated Novel", shared, 0)
    save_entities(
        {"entities": [{"entity_id": shared, "canonical_name": "Michael", "type": "character",
                       "aliases": [], "book_ids": [book1, book2]}]},
        root,
    )

    result = split_cross_book_entity(shared, root)

    assert result.new_entity_ids == []
    assert result.dropped_book_ids == [book2]
    entities = load_entities(root)["entities"]
    assert len(entities) == 1
    assert entities[0]["book_ids"] == [book1]


def test_split_preserves_every_fact(tmp_path: Path) -> None:
    """The repair must be lossless - it only relabels which entity a fact
    belongs to, never drops or duplicates a record."""
    root = tmp_path / "library"
    shared = "concept-abc12345"
    book1 = _book_with_entity(root, tmp_path, "One Book", shared, 4)
    book2 = _book_with_entity(root, tmp_path, "Another Book", shared, 3)
    save_entities(
        {"entities": [{"entity_id": shared, "canonical_name": "Power", "type": "concept",
                       "aliases": [], "book_ids": [book1, book2]}]},
        root,
    )
    before = {
        b: [json.loads(line)["statement"]
            for line in (root / b / "facts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        for b in (book1, book2)
    }

    split_cross_book_entity(shared, root)

    after = {
        b: [json.loads(line)["statement"]
            for line in (root / b / "facts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        for b in (book1, book2)
    }
    assert after == before
