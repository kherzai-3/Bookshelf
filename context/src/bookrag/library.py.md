---
source: src/bookrag/library.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 572d0846aa48b61a669a3cf26cf51356402e5170
---

## Purpose
Library-wide inspection and maintenance, sitting above `storage.py` (one
book's persistence) and `extract/resolve.py` (the global entity registry):
list/show what's in the library and how far extraction has gotten, remove a
book cleanly, and a read-only-by-default consistency check ("doctor") for
drift accumulated by hand-editing library files directly - exactly the kind
of cleanup done manually several times earlier this project (a stale
`index.json` entry after a directory was deleted outside the CLI, orphaned
`entities.json` entries with zero facts actually backing them). `cli.py`'s
`list`/`show`/`remove`/`doctor` subcommands are thin wrappers around this
module's functions.

## Public Interface
- `BookSummary` (dataclass) — `book_id, title, author, series, orphaned,
  content_type, chapter_count, fact_count, chapters_extracted, entity_count`,
  plus a `partial` property (see Key Decisions).
- `list_books(root=None) -> list[BookSummary]` — one summary per
  `index.json` entry.
- `show_book(book_id, root=None) -> BookSummary` — raises `ValueError` if
  `book_id` isn't in `index.json` at all.
- `RemoveResult` (dataclass) — `removed_directory, removed_index_entry,
  entities_pruned, entities_deleted`.
- `remove_book(book_id, root=None) -> RemoveResult` — deletes
  `data/library/<book_id>/`, its `index.json` entry, and prunes `book_id`
  from every entity's `book_ids` in `entities.json` (deleting any entity
  this leaves with none). Raises `ValueError` only if `book_id` is unknown
  to *both* the index and the filesystem - otherwise cleans up whichever
  parts of it actually exist (handles the orphaned-index-entry case too).
- `DoctorReport` (dataclass) — `orphaned_index_entries: list[str],
  stale_entity_book_refs: list[tuple[entity_id, book_id]],
  orphaned_entities: list[str], fixed: bool`.
- `run_doctor(root=None, fix=False) -> DoctorReport` — read-only by default;
  `fix=True` also applies the cleanup (see Key Decisions for exactly what).

## Key Decisions
- **"How far extraction reached" is `max(chapter_index) + 1` from
  `facts.jsonl`, not a count of chapters that have at least one fact.**
  These genuinely differ on real data: a fully successful `extract_book` run
  still writes zero fact records for a chapter `extract.pipeline` decided
  was too short to plausibly be narrative (front matter, a one-line
  interstitial) - confirmed directly against Ranger's Apprentice, which has
  facts for 72 of its 75 chapters but the highest `chapter_index` present is
  74 (the run reached the end; the 3 zero-fact chapters are legitimately
  non-narrative). Counting only chapters-with-facts would have wrongly
  reported a fully-extracted book as partial. This heuristic has its own
  blind spot, not yet hit in practice: if the very *last* chapter is itself
  one of the zero-fact ones, a complete run would still read as one chapter
  short. There's no persisted "chapters actually attempted" record to do
  better than this without adding one - see Open Questions.
- **`BookSummary.partial`** is `True` only when `chapters_extracted` is
  known and less than `chapter_count` - `None` (never extracted) is
  deliberately not "partial", it's a separate state (`fact_count is None`).
- **`remove_book`/`run_doctor --fix` both delete an entity outright once its
  `book_ids` becomes empty** - nothing else could ever reference it again
  once its only book(s) are gone. This reuses
  `resolve.prune_book_from_entities`, the mutation-in-place counterpart to
  `resolve_entity`'s "add a book_id" - kept in `resolve.py`, not duplicated
  here, since that's where `entities.json`'s shape is already understood.
- **`run_doctor`'s three checks are independent, not a single "is this
  entity valid" pass**: `orphaned_index_entries` (index says a book exists,
  filesystem disagrees), `stale_entity_book_refs` (an entity still lists a
  `book_id` that's gone - reported even for an otherwise-healthy entity with
  other valid book_ids, since the stale ref itself is real leftover data),
  and `orphaned_entities` (zero facts reference this entity in any book that
  *does* still exist - the stronger, "genuinely useless" check, requiring an
  actual `facts.jsonl` scan per book, not just a `book_ids` list check).
  `--fix` prunes stale refs and deletes orphaned entities as two separate
  actions on the same entity where applicable.
- **`remove_book` is deliberately tolerant of partial/orphaned state**
  (works if only the directory exists, only the index entry exists, or
  both) rather than requiring a fully-consistent book first - this is what
  lets `bookrag doctor --fix`'s orphaned-index-entry cleanup and a normal
  `bookrag remove` share the same underlying logic instead of needing two
  separate code paths.

## Dependencies
- Internal: `bookrag.storage` (`library_root`, `load_index`, `load_metadata`,
  `remove_from_index`), `bookrag.extract.resolve` (`load_entities`,
  `save_entities`, `prune_book_from_entities`)

## Data Contracts
- Reads `facts.jsonl` records only for their `chapter_index`/`entity_id`
  fields (see `extract/pipeline.py`'s context doc for the full record
  shape) - never touches `category`/`statement`.

## Open Questions / TODOs
- The `max(chapter_index) + 1` completion heuristic (see Key Decisions) is
  an approximation, not a real "chapters attempted" record - it would be
  made exact by `extract_book` persisting its own progress, which is
  exactly what the planned resumable-extraction feature needs anyway (see
  `extract/pipeline.py`'s context doc). Worth unifying when that's built,
  rather than solving the same problem twice.
- `resolve_entity` (see `extract/resolve.py`'s context doc) matches
  globally across the whole library, not scoped to a series - `doctor`'s
  `orphaned_entities` check doesn't attempt to detect a *coincidental*
  cross-book name collision (two unrelated books' same-named, same-typed
  entities silently sharing one `entity_id`); it only checks whether an
  entity has zero facts anywhere, which a collided entity would still pass.
  No real collision has been observed in the current library.
