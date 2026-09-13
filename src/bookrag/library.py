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
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from bookrag.extract.resolve import load_entities, match_key, prune_book_from_entities, save_entities
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


def _fact_count_for_entity(root: Path, entity: dict) -> int:
    """Counts facts naming this exact entity_id, across every book it's
    linked to - used to pick a sensible default "keep this one" candidate
    when merging duplicates (see merge_entities) and to show cluster sizes
    in bookrag doctor's report."""
    count = 0
    for book_id in entity["book_ids"]:
        facts_path = root / book_id / "facts.jsonl"
        if not facts_path.exists():
            continue
        with facts_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and json.loads(line)["entity_id"] == entity["entity_id"]:
                    count += 1
    return count


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
class DuplicateEntity:
    entity_id: str
    canonical_name: str
    type: str
    book_ids: list[str]
    fact_count: int


def _duplicate_clusters(entities: dict, root: Path) -> list[list[DuplicateEntity]]:
    groups: dict[str, list[dict]] = {}
    for entity in entities["entities"]:
        groups.setdefault(match_key(entity["canonical_name"]), []).append(entity)

    clusters = []
    for group in groups.values():
        if len(group) > 1:
            clusters.append(
                [
                    DuplicateEntity(
                        entity_id=e["entity_id"],
                        canonical_name=e["canonical_name"],
                        type=e["type"],
                        book_ids=e["book_ids"],
                        fact_count=_fact_count_for_entity(root, e),
                    )
                    for e in group
                ]
            )
    return clusters


def detect_duplicate_entities(root: Path | None = None) -> list[list[DuplicateEntity]]:
    """Groups entities whose canonical_name normalizes to the same
    extract.resolve.match_key - deliberately regardless of entity_type,
    unlike resolve_entity's own type-scoped matching. Type drift across
    chapters is exactly one of the two ways a real duplicate cluster forms
    (see extract/pipeline.py's known_entity_types for the fix that
    prevents *new* drift going forward; this is what finds clusters that
    already exist). Detection only, on purpose - bookrag doctor's --fix
    never auto-merges these, unlike its other three checks, since merging
    is a much higher-stakes, harder-to-reverse action than deleting an
    orphan."""
    root = root or library_root()
    return _duplicate_clusters(load_entities(root), root)


@dataclass
class MergeResult:
    kept_entity_id: str
    merged_entity_ids: list[str]
    facts_rewritten: int


def merge_entities(entity_ids: list[str], keep: str | None = None, root: Path | None = None) -> MergeResult:
    """Merges 2+ existing entities into one: rewrites every fact record's
    entity_id (in every book directory any of them reference) to point at
    the kept entity, unions book_ids, folds the merged-away entities'
    canonical names/aliases into the kept entity's aliases (this is what
    finally populates that otherwise-dead field - see resolve.py's context
    doc), and deletes the merged-away entity records. `keep` defaults to
    whichever entity has the most facts, matching the real dominant-entity
    pattern already observed in a real duplicate cluster (one entity held
    73% of the group's facts)."""
    root = root or library_root()
    entities = load_entities(root)
    by_id = {e["entity_id"]: e for e in entities["entities"]}

    group = [by_id[eid] for eid in entity_ids if eid in by_id]
    if len(group) < 2:
        raise ValueError("merge_entities needs at least two existing entity_ids")

    if keep is None:
        keep = max(group, key=lambda e: _fact_count_for_entity(root, e))["entity_id"]
    if keep not in by_id or keep not in entity_ids:
        raise ValueError(f"keep={keep!r} must be one of the entity_ids being merged")

    kept = by_id[keep]
    merged_away = [e for e in group if e["entity_id"] != keep]

    facts_rewritten = 0
    all_book_ids = list(kept["book_ids"])
    for entity in merged_away:
        for book_id in entity["book_ids"]:
            if book_id not in all_book_ids:
                all_book_ids.append(book_id)
            facts_path = root / book_id / "facts.jsonl"
            if not facts_path.exists():
                continue
            lines = facts_path.read_text(encoding="utf-8").splitlines()
            rewritten_lines = []
            for line in lines:
                record = json.loads(line)
                if record["entity_id"] == entity["entity_id"]:
                    record["entity_id"] = keep
                    facts_rewritten += 1
                rewritten_lines.append(json.dumps(record))
            facts_path.write_text("\n".join(rewritten_lines) + "\n", encoding="utf-8")

        # Every distinct surface form the merged-away entity carried
        # becomes an alias of the kept entity - not gated on match_key,
        # which only decides *merge-worthiness*, not string identity: "The
        # Wargals" and "Wargals" share a match_key but are still two real,
        # useful surface forms worth recording once merged. Only an exact
        # (case-insensitive) match to the kept entity's own canonical_name
        # is skipped, to avoid a pointless self-alias.
        if (
            entity["canonical_name"].lower() != kept["canonical_name"].lower()
            and entity["canonical_name"] not in kept["aliases"]
        ):
            kept["aliases"].append(entity["canonical_name"])
        for alias in entity["aliases"]:
            if alias.lower() != kept["canonical_name"].lower() and alias not in kept["aliases"]:
                kept["aliases"].append(alias)

    kept["book_ids"] = all_book_ids
    merged_ids = {e["entity_id"] for e in merged_away}
    entities["entities"] = [e for e in entities["entities"] if e["entity_id"] not in merged_ids]
    save_entities(entities, root)

    return MergeResult(kept_entity_id=keep, merged_entity_ids=sorted(merged_ids), facts_rewritten=facts_rewritten)


@dataclass
class CrossBookEntity:
    entity_id: str
    canonical_name: str
    type: str
    # book_id -> how many facts in that book point at this entity. A book
    # with 0 is a leftover book_ids entry with nothing behind it (see
    # split_cross_book_entity), not a real second character.
    facts_per_book: dict[str, int]


@dataclass
class SplitResult:
    original_entity_id: str
    new_entity_ids: list[str]
    facts_rewritten: int
    dropped_book_ids: list[str]


def _series_name(root: Path, book_id: str) -> str | None:
    for book in load_index(root)["books"]:
        if book["book_id"] == book_id:
            series = book.get("series")
            return series["name"] if series else None
    return None


def detect_cross_book_entities(root: Path | None = None) -> list[CrossBookEntity]:
    """Entities claimed by two or more books that are NOT part of one
    series - i.e. two unrelated books' characters fused into a single
    identity.

    Before `resolve_entity` took a `scope` (see extract/resolve.py's context
    doc), its match loop ran over every entity from every book ever
    ingested, so any two books sharing a common name merged. Scoping stops
    new ones; it cannot undo existing ones, because a re-extraction resolves
    against the same registry. This finds them.

    Sharing an identity across books in the *same series* is the intended
    behaviour and is never reported here.
    """
    root = root or library_root()
    entities = load_entities(root)
    found = []
    for entity in entities["entities"]:
        book_ids = entity["book_ids"]
        if len(book_ids) < 2:
            continue
        series = {_series_name(root, bid) for bid in book_ids}
        # One shared, non-None series name means this is legitimate.
        if len(series) == 1 and None not in series:
            continue
        found.append(
            CrossBookEntity(
                entity_id=entity["entity_id"],
                canonical_name=entity["canonical_name"],
                type=entity["type"],
                facts_per_book={
                    bid: sum(
                        1
                        for line in (root / bid / "facts.jsonl").read_text(encoding="utf-8").splitlines()
                        if line.strip() and json.loads(line)["entity_id"] == entity["entity_id"]
                    )
                    if (root / bid / "facts.jsonl").exists()
                    else 0
                    for bid in book_ids
                },
            )
        )
    return found


def split_cross_book_entity(entity_id: str, root: Path | None = None) -> SplitResult:
    """Gives each book its own entity record, undoing a wrong merge.

    Losslessly mechanical, unlike the dangling-fact-reference case doctor
    deliberately refuses to auto-repair: facts are already partitioned by
    book file, so which book each fact belongs to is not a guess. Every book
    keeps the same canonical_name and type - they merged precisely because
    they spell the same.

    The book with the most facts keeps the original entity_id, so the common
    case rewrites the fewest records (and matches merge_entities' own
    keep-the-dominant-entity convention). A book_id with **zero** facts gets
    no entity at all, just dropped: it is a leftover reference, not a second
    character. That happens after `extract --restart`, which truncates
    facts.jsonl but leaves entities.json alone, so a book_id recorded by the
    pre-restart run outlives every fact that justified it.
    """
    root = root or library_root()
    entities = load_entities(root)
    by_id = {e["entity_id"]: e for e in entities["entities"]}
    if entity_id not in by_id:
        raise ValueError(f"No entity with id {entity_id!r}")

    entity = by_id[entity_id]
    counts = {
        bid: sum(
            1
            for line in (root / bid / "facts.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line)["entity_id"] == entity_id
        )
        if (root / bid / "facts.jsonl").exists()
        else 0
        for bid in entity["book_ids"]
    }
    with_facts = [bid for bid, n in counts.items() if n]
    dropped = sorted(bid for bid, n in counts.items() if not n)

    if len(with_facts) < 2:
        # Nothing to split - at most one book actually has content. Still
        # worth dropping the unbacked book_ids, which is the whole repair
        # in this case.
        entity["book_ids"] = with_facts or entity["book_ids"][:1]
        save_entities(entities, root)
        return SplitResult(entity_id, [], 0, dropped)

    keeper = max(with_facts, key=lambda bid: counts[bid])
    entity["book_ids"] = [keeper]

    new_ids: list[str] = []
    facts_rewritten = 0
    for book_id in sorted(bid for bid in with_facts if bid != keeper):
        new_id = f"{entity['type']}-{uuid.uuid4().hex[:8]}"
        new_ids.append(new_id)
        facts_path = root / book_id / "facts.jsonl"
        rewritten = []
        for line in facts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record["entity_id"] == entity_id:
                record["entity_id"] = new_id
                facts_rewritten += 1
            rewritten.append(json.dumps(record))
        facts_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        entities["entities"].append(
            {
                "entity_id": new_id,
                "canonical_name": entity["canonical_name"],
                "type": entity["type"],
                # Deliberately not copied: an alias could have come from
                # either book, and this cannot know which. Losing an alias
                # costs a retrieval near-miss; inventing one asserts a name
                # a book may never have used.
                "aliases": [],
                "book_ids": [book_id],
            }
        )

    save_entities(entities, root)
    return SplitResult(entity_id, new_ids, facts_rewritten, dropped)


@dataclass
class DoctorReport:
    orphaned_index_entries: list[str]  # book_id: in index.json, no directory/metadata on disk
    stale_entity_book_refs: list[tuple[str, str]]  # (entity_id, book_id) book_id no longer exists
    orphaned_entities: list[str]  # entity_id: zero facts reference it in any book that still exists
    duplicate_entity_groups: list[list[DuplicateEntity]]  # entities that look like the same real thing
    # (book_id, entity_id) for facts pointing at an entity the registry has no
    # record of - the exact inverse of orphaned_entities, and the damaging
    # direction. An orphaned entity is a harmless empty row; a dangling fact
    # reference is real content that renders as a raw id and is invisible to
    # entity-name retrieval. Never auto-repaired: the name is unrecoverable
    # (a fact stores only the entity_id), so the only honest fixes are
    # re-extracting those chapters or accepting the loss - both the user's
    # call, not a cleanup pass's.
    unnamed_fact_refs: list[tuple[str, str]]
    # Entities claimed by two or more books with no series relationship -
    # two unrelated books' characters fused into one identity by the
    # unscoped resolve_entity this library predates. Reported but never
    # touched by --fix, same posture as duplicate_entity_groups: splitting
    # rewrites fact records across book files, which is a higher-stakes
    # action than deleting an orphan. `bookrag doctor --split-cross-book`
    # applies it.
    cross_book_entities: list[CrossBookEntity] = field(default_factory=list)
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

    duplicate_groups = _duplicate_clusters(entities, root)
    cross_book = detect_cross_book_entities(root)

    known_entity_ids = {e["entity_id"] for e in entities["entities"]}
    unnamed_fact_refs = sorted(
        (bid, entity_id)
        for bid, referenced in referenced_by_book.items()
        for entity_id in referenced - known_entity_ids
    )

    if not fix:
        return DoctorReport(
            orphaned_index_entries,
            stale_refs,
            orphaned_entities,
            duplicate_groups,
            unnamed_fact_refs,
            cross_book_entities=cross_book,
            fixed=False,
        )

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

    return DoctorReport(
        orphaned_index_entries,
        stale_refs,
        orphaned_entities,
        duplicate_groups,
        unnamed_fact_refs,
        cross_book_entities=cross_book,
        fixed=True,
    )
