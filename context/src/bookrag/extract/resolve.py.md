---
source: src/bookrag/extract/resolve.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 92ea7629ce5034c41334ff9815d67ae4aaacfd5f
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
