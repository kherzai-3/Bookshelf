"""Library-wide inspection and maintenance: list/show what's been ingested
and how far extraction has gotten, remove a book cleanly (including its
entities.json references), and a read-only-by-default consistency check
("doctor") for the kind of drift that's accumulated by hand this project's
own development - a stale index.json entry left behind after a directory was
deleted outside the CLI, or an entity with zero facts actually backing it
across any book that still exists."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from bookrag.extract.resolve import load_entities, prune_book_from_entities, save_entities
from bookrag.storage import library_root, load_index, load_metadata, remove_from_index


@dataclass
class BookSummary:
    book_id: str
    title: str
    author: str | None
    series: dict | None
    orphaned: bool  # index.json entry exists, but its directory/metadata doesn't
    content_type: str | None = None
    chapter_count: int | None = None
    fact_count: int | None = None  # None means never extracted (no facts.jsonl)
    chapters_extracted: int | None = None  # how far the run reached: max(chapter_index) + 1
    entity_count: int = 0

    @property
    def partial(self) -> bool:
        """True when extraction hasn't reached the end of the book yet -
        e.g. a deliberate sample extraction, or a run interrupted partway
        through (bookrag extract has no resume, so this is how that state
        looks: real facts for chapters 0..N, nothing beyond)."""
        return (
            self.chapters_extracted is not None
            and self.chapter_count is not None
            and self.chapters_extracted < self.chapter_count
        )


def _referenced_entity_ids(root: Path, book_id: str) -> set[str]:
    facts_path = root / book_id / "facts.jsonl"
    if not facts_path.exists():
        return set()
    ids = set()
    with facts_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.add(json.loads(line)["entity_id"])
    return ids


def _extraction_stats(root: Path, book_id: str) -> tuple[int, int] | None:
    """(fact_count, chapters_extracted) from facts.jsonl, or None if the book
    has never been extracted at all. chapters_extracted is how far the run
    *reached* - max(chapter_index) + 1, not a count of chapters that
    produced at least one fact. Those two differ for real books: a genuinely
    complete extract_book run still writes zero facts for a chapter
    extract.pipeline decided was too short to plausibly be narrative (front
    matter, a one-line interstitial), so counting only chapters with facts
    would wrongly read a fully-extracted book as partial (confirmed on real
    data: Ranger's Apprentice has facts for 72 of 75 chapters, but the
    highest chapter_index present is 74 - the run reached the end; the 3
    zero-fact chapters are legitimately non-narrative, not unprocessed)."""
    facts_path = root / book_id / "facts.jsonl"
    if not facts_path.exists():
        return None
    fact_count = 0
    max_index = -1
    with facts_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            fact_count += 1
            max_index = max(max_index, json.loads(line)["chapter_index"])
    return fact_count, max_index + 1


def _summarize(entry: dict, root: Path, entities: dict) -> BookSummary:
    book_id = entry["book_id"]
    book_dir = root / book_id
    if not book_dir.exists():
        return BookSummary(
            book_id=book_id, title=entry["title"], author=entry["author"],
            series=entry["series"], orphaned=True,
        )
    try:
        metadata = load_metadata(book_id, root)
    except FileNotFoundError:
        return BookSummary(
            book_id=book_id, title=entry["title"], author=entry["author"],
            series=entry["series"], orphaned=True,
        )

    entity_count = sum(1 for e in entities["entities"] if book_id in e["book_ids"])
    stats = _extraction_stats(root, book_id)
    return BookSummary(
        book_id=book_id,
        title=entry["title"],
        author=entry["author"],
        series=entry["series"],
        orphaned=False,
        content_type=metadata.get("content_type", "fiction"),
        chapter_count=metadata.get("chapter_count"),
        fact_count=stats[0] if stats else None,
        chapters_extracted=stats[1] if stats else None,
        entity_count=entity_count,
    )


def list_books(root: Path | None = None) -> list[BookSummary]:
    root = root or library_root()
    entities = load_entities(root)
    return [_summarize(entry, root, entities) for entry in load_index(root)["books"]]


def show_book(book_id: str, root: Path | None = None) -> BookSummary:
    root = root or library_root()
    entry = next((b for b in load_index(root)["books"] if b["book_id"] == book_id), None)
    if entry is None:
        raise ValueError(f"no such book in the library: {book_id!r}")
    return _summarize(entry, root, load_entities(root))


@dataclass
class RemoveResult:
    removed_directory: bool
    removed_index_entry: bool
    entities_pruned: int
    entities_deleted: int


def remove_book(book_id: str, root: Path | None = None) -> RemoveResult:
    """Deletes data/library/<book_id>/ (if present), its index.json entry
    (if present), and prunes book_id from every entity's book_ids in
    entities.json, deleting any entity this leaves with zero book_ids.
    Works even on a partial/orphaned state (e.g. directory already gone but
    an index.json entry remains) - raises only if book_id is unknown to
    both the index and the filesystem."""
    root = root or library_root()
    book_dir = root / book_id
    dir_existed = book_dir.exists()

    index_had_entry = any(b["book_id"] == book_id for b in load_index(root)["books"])
    if not dir_existed and not index_had_entry:
        raise ValueError(f"no such book in the library: {book_id!r}")

    if dir_existed:
        shutil.rmtree(book_dir)
    removed_index_entry = remove_from_index(book_id, root)

    entities = load_entities(root)
    pruned, deleted = prune_book_from_entities(entities, book_id)
    if pruned:
        save_entities(entities, root)

    return RemoveResult(
        removed_directory=dir_existed,
        removed_index_entry=removed_index_entry,
        entities_pruned=pruned,
        entities_deleted=deleted,
    )


@dataclass
class DoctorReport:
    orphaned_index_entries: list[str]  # book_id: in index.json, no directory/metadata on disk
    stale_entity_book_refs: list[tuple[str, str]]  # (entity_id, book_id) book_id no longer exists
    orphaned_entities: list[str]  # entity_id: zero facts reference it in any book that still exists
    fixed: bool = False


def run_doctor(root: Path | None = None, fix: bool = False) -> DoctorReport:
    root = root or library_root()
    index = load_index(root)
    entities = load_entities(root)

    valid_book_ids = {b["book_id"] for b in index["books"] if (root / b["book_id"]).exists()}
    orphaned_index_entries = [b["book_id"] for b in index["books"] if b["book_id"] not in valid_book_ids]

    stale_refs: list[tuple[str, str]] = []
    for entity in entities["entities"]:
        for bid in entity["book_ids"]:
            if bid not in valid_book_ids:
                stale_refs.append((entity["entity_id"], bid))

    referenced_by_book = {bid: _referenced_entity_ids(root, bid) for bid in valid_book_ids}
    orphaned_entities = [
        entity["entity_id"]
        for entity in entities["entities"]
        if not any(
            bid in valid_book_ids and entity["entity_id"] in referenced_by_book[bid]
            for bid in entity["book_ids"]
        )
    ]

    if not fix:
        return DoctorReport(orphaned_index_entries, stale_refs, orphaned_entities, fixed=False)

    for book_id in orphaned_index_entries:
        remove_from_index(book_id, root)

    kept = []
    for entity in entities["entities"]:
        if entity["entity_id"] in orphaned_entities:
            continue
        entity["book_ids"] = [bid for bid in entity["book_ids"] if bid in valid_book_ids]
        kept.append(entity)
    entities["entities"] = kept
    save_entities(entities, root)

    return DoctorReport(orphaned_index_entries, stale_refs, orphaned_entities, fixed=True)
