---
source: src/bookrag/library.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 5f09854ed384bd606197b077ad69b52ffcf7bb73
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
- `DuplicateEntity` (dataclass) — `entity_id, canonical_name, type,
  book_ids, fact_count` - one member of a possible-duplicate cluster.
- `detect_duplicate_entities(root=None) -> list[list[DuplicateEntity]]` —
  groups entities by `extract.resolve.match_key(canonical_name)`,
  **regardless of `entity_type`** (unlike `resolve_entity`'s own matching -
  see Key Decisions), returns only groups with more than one entity.
- `MergeResult` (dataclass) — `kept_entity_id, merged_entity_ids: list[str],
  facts_rewritten: int`.
- `merge_entities(entity_ids, keep=None, root=None) -> MergeResult` —
  merges 2+ existing entities into one (see Key Decisions for exactly
  what it rewrites). Raises `ValueError` if fewer than two of
  `entity_ids` actually exist, or if `keep` isn't one of them.
- `DoctorReport` (dataclass) — `orphaned_index_entries: list[str],
  stale_entity_book_refs: list[tuple[entity_id, book_id]],
  orphaned_entities: list[str], duplicate_entity_groups:
  list[list[DuplicateEntity]], fixed: bool`.
- `run_doctor(root=None, fix=False) -> DoctorReport` — read-only by default;
  `fix=True` also applies the cleanup (see Key Decisions for exactly what -
  `duplicate_entity_groups` is never included in what `fix` touches).

## Key Decisions
- **`detect_duplicate_entities` deliberately ignores `entity_type` when
  grouping**, unlike `resolve_entity`'s own type-scoped matching. Real
  motivating case: one creature ("Wargal(s)") had fragmented into 5
  catalog entities across *both* name spelling and `entity_type`
  (`character`/`setting`/`theme`) - a type-scoped detector would only ever
  find same-type duplicates and miss most of that real cluster. A real
  full-library `bookrag doctor` run found 12 such clusters, several
  type-crossing (a publisher name typed as both `setting` and
  `character`; "Skandians" split three ways) and at least one that was
  pure name-variant with **no** type drift at all ("Implementation
  Intention"/"Implementation Intentions", both already `concept`) -
  confirming `match_key` normalization has real value independent of the
  type-drift fix in `extract/pipeline.py`.
- **Detection only - `bookrag doctor --fix` never auto-merges duplicate
  clusters**, unlike its other three checks (which are all safe,
  reversible-in-spirit cleanups of clearly-dead data). Merging picks a
  winner and permanently rewrites fact ownership - a real, consequential
  judgment call that needs a human to confirm, not a blind default action.
  `merge_entities` is exposed separately (`bookrag doctor
  --merge-duplicates`, confirmed per cluster unless `--yes`).
- **`merge_entities` picks the most-facts entity as `keep` by default** -
  matches the real, lopsided pattern already observed (one real cluster's
  dominant entity held 73% of the group's facts). Every merged-away
  entity's `canonical_name` and its own `aliases` become aliases of the
  kept entity - gated only on an exact (case-insensitive) match to the
  kept entity's own name, **not** on `match_key` equality, since two
  surface forms sharing a `match_key` (e.g. "Wargals"/"The Wargals") are
  still two real, distinct strings worth recording once merged - this is
  what finally populates `aliases`, a field nothing else in the codebase
  ever writes to (see `extract/resolve.py`'s context doc). Facts are
  rewritten in every book directory any merged entity referenced, not just
  one - a real entity can span multiple books via `book_ids`.
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

## `unnamed_fact_refs` - facts pointing at an unregistered entity
The inverse of `orphaned_entities`, and the damaging direction of the same
inconsistency. An orphaned entity is a harmless empty registry row; a fact
referencing an entity the registry has no record of is **real content that
renders as a raw id and cannot be found by name**.

`--fix` deliberately leaves these alone, unlike the three checks it does
repair. The name is unrecoverable (a fact stores only the `entity_id`), so the
only honest repairs are re-extracting the affected chapters or accepting the
loss - both the user's call, not a cleanup pass's. Deleting the facts would be
destroying real content to satisfy a consistency check.

Found on the project's own library: 14 ids covering 38 facts, all from
chapters 4-10, caused by `extract/pipeline.py` saving the registry only in a
`finally` that an abrupt kill never reached (fixed there; see that context
doc).
