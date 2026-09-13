---
source: tests/test_resolve.py
last_synced: 2026-09-13T16:40:00Z
source_hash: 6b95bf1b11277b263523c49b805e506bb4e63bf6
---

## Purpose
Covers `extract.resolve.resolve_entity`: new-entity creation, case-insensitive
exact match, alias match, and type-scoped separation (same name, different
`entity_type`). Also covers `match_key`'s normalization (via `resolve_entity`):
the real "Wargal"/"Wargals"/"The Wargals"/"The Wargal" case unifies to one
entity within a type, and confirms this normalization doesn't relax the
existing type-scoping (the same name still resolves separately per
`entity_type`).

Since the identity-scoping change, four tests pin down *which books* may share
an entity — the question that used to have no answer at all:
- `test_a_later_series_book_reuses_the_earlier_books_entity` — a book given an
  explicit `scope` reuses an earlier series book's entity, so a character
  accumulates facts across a series.
- `test_unrelated_books_sharing_a_name_stay_separate_entities` — two unrelated
  books that each introduce a same-named, same-typed entity get separate ids.
- `test_scope_defaults_to_the_book_itself_rather_than_every_book` — omitting
  `scope` means the narrow default (just this book), never the whole library.
- `test_scope_does_not_override_type_scoping` — a shared scope still cannot fuse
  two different `entity_type`s.

**This doc previously claimed the opposite** — that "a repeat resolution from a
different `book_id` appends to that entity's `book_ids`" — which described the
global-merge behaviour removed in `0950659`. The test encoding it was renamed,
not deleted, so the stale description survived the change.
