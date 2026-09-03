---
source: tests/test_resolve.py
last_synced: 2026-09-02T00:00:00Z
source_hash: d43575b33eae9f3daa86515396f38e705c62eae9
---

## Purpose
Covers `extract.resolve.resolve_entity`: new-entity creation, case-insensitive
exact match, alias match, type-scoped separation (same name, different
`entity_type`), and that a repeat resolution from a different `book_id`
appends to that entity's `book_ids` rather than duplicating it.
