---
source: tests/test_resolve.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 9bc5c629e067d42514b68933cb5dee97f4fef948
---

## Purpose
Covers `extract.resolve.resolve_entity`: new-entity creation, case-insensitive
exact match, alias match, type-scoped separation (same name, different
`entity_type`), and that a repeat resolution from a different `book_id`
appends to that entity's `book_ids` rather than duplicating it. Also
covers `_match_key`'s normalization (via `resolve_entity`): the real
"Wargal"/"Wargals"/"The Wargals"/"The Wargal" case unifies to one entity
within a type, and confirms this normalization doesn't relax the existing
type-scoping (the same name still resolves separately per `entity_type`).
