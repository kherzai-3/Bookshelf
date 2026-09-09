---
source: src/bookrag/extract/resolve.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 1aa924ed7b2a27776b3132c9ed3fd0713a5fa5a5
---

## Purpose
Resolves a raw extracted `entity_name` string to a stable `entity_id`
against the global entity registry (`data/library/entities.json`), and manages that
registry's load/save.

## Public Interface
- `entities_path(root=None) -> Path` — `<root>/entities.json`.
- `load_entities(root=None) -> dict` — `{"entities": []}` if the file
  doesn't exist yet.
- `save_entities(entities: dict, root=None) -> None`
- `resolve_entity(name: str, entity_type: str, book_id: str, entities: dict)
  -> str` — **mutates `entities` in place** (adds a new entry, or records
  `book_id` against an existing match) and returns the resolved
  `entity_id`. Matches via `_match_key` (see Key Decisions), not raw
  string equality.
- `prune_book_from_entities(entities: dict, book_id: str) -> tuple[int, int]`
  — **mutates `entities` in place**: removes `book_id` from every entity's
  `book_ids`, dropping any entity this leaves with none. Returns
  `(entities_pruned, entities_deleted)`. Added for `library.remove_book`/
  `bookrag doctor`'s cleanup - the inverse operation of `resolve_entity`
  adding a `book_id`.

## Key Decisions
- **No real fuzzy/semantic coreference** - "the old man" will not
  automatically link to "Ishmael". Documented as a known limitation
  (README's Known Limitations) rather than solved here - same posture as
  the epub/pdf ingestion heuristics: ship something reasonable, make the
  gap visible, improve iteratively. Aliases can be added to
  `entities.json` by hand today.
- **`_match_key(name)` adds light, comparison-only normalization** (strip a
  leading "the ", strip a trailing "s") on top of the case-insensitive
  exact match, used for both `canonical_name` and every alias.
  Deliberately narrow, not real fuzzy matching (no edit-distance/
  similarity library) - real bug found and fixed by this: a single
  creature ("Wargal(s)" in a real book) had fragmented into 5 entities
  across name variants ("Wargals"/"The Wargals") *and* entity_types
  (see the type-drift item below, and `extract/pipeline.py`'s
  `known_entity_types` for the other half of that fix). A broader
  similarity library was deliberately not added here - real risk of
  false-positive merges (two genuinely different names colliding) without
  much more careful thresholding/testing than this narrow, high-confidence
  rule needs.
- Matching is scoped by `entity_type` - a character and a setting with the
  same name (e.g. "Nantucket" the place vs. a character nicknamed
  "Nantucket") resolve to two separate entities.
- `entity_id` format is `f"{entity_type}-{uuid4().hex[:8]}"` - readable
  prefix, no collision-handling needed given the fixed-length random suffix.

## Data Contracts
- Entity record: `{entity_id, canonical_name, type, aliases: [str],
  book_ids: [str]}`.

## Dependencies
- Internal: `bookrag.storage.library_root`

## Open Questions / TODOs
- **`resolve_entity` matches globally across the *entire* library, not
  scoped to a series or otherwise related books** - noticed while building
  `library.py`. Two completely unrelated books that both introduce a
  character of the same name and `entity_type` (e.g. two different novels
  each with a "Will") will silently resolve to the *same* `entity_id`,
  because matching only checks `(name, entity_type)`, never whether the
  books are actually related. This is intentional for the series case
  (`storage.series_reading_order` relies on facts about the same character
  accumulating across sequential books) but was never scoped to *only* the
  series case - it currently applies library-wide. Not a spoiler-safety bug
  (each book's own `facts.jsonl` stays correctly scoped by `chapter_index`
  regardless), but it does mean `entities.json`'s registry can conflate two
  unrelated characters' identities. No real collision has been observed
  yet (the current library's books don't share character names) - flagged
  here so it's not re-discovered from scratch if one ever does.
