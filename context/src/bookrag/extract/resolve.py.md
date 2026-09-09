---
source: src/bookrag/extract/resolve.py
last_synced: 2026-09-09T00:00:00Z
source_hash: b7bd4b1a179c8adc29adf8c59c2795ccfbce9414
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
  `entity_id`.
- `prune_book_from_entities(entities: dict, book_id: str) -> tuple[int, int]`
  — **mutates `entities` in place**: removes `book_id` from every entity's
  `book_ids`, dropping any entity this leaves with none. Returns
  `(entities_pruned, entities_deleted)`. Added for `library.remove_book`/
  `bookrag doctor`'s cleanup - the inverse operation of `resolve_entity`
  adding a `book_id`.

## Key Decisions
- **No fuzzy/semantic coreference in v1** - resolution is case-insensitive
  exact match against a canonical name or a known alias only. "the old man"
  will not automatically link to "Ishmael". Documented as a known
  limitation (README's Known Limitations) rather than solved here - same
  posture as the epub/pdf ingestion heuristics: ship something reasonable,
  make the gap visible, improve iteratively. Aliases can be added to
  `entities.json` by hand today.
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
