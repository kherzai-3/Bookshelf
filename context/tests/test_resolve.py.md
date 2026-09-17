---
source: tests/test_resolve.py
last_synced: 2026-09-17T14:28:47Z
source_hash: 66be93f2cef4ee6b15f68487630740934022143b
---

## Purpose
Covers `extract.resolve.resolve_entity`: new-entity creation, case-insensitive
exact match, alias match, and type-scoped separation (same name, different
`entity_type`). Also covers `match_key`'s normalization (via `resolve_entity`):
the real "Wargal"/"Wargals"/"The Wargals"/"The Wargal" case unifies to one
entity within a type, and confirms this normalization doesn't relax the
existing type-scoping (the same name still resolves separately per
`entity_type`).

Two further tests cover `group_name_variants`, which partitions names into
groups that plausibly name one person:
- `..._keeps_two_peoples_name_pairs_apart` is the property the function exists
  for. Its caller (`ingest.vocatives.auto_link_plan`) links without asking at
  ingest, so flattening two pairs into one set declared two first-person
  narrators to be one character.
- `..._is_transitive_and_keeps_a_loner_alone` pins that three spellings of one
  name are one group rather than overlapping pairs, and that an unrelated name
  comes back as a group of one — which callers requiring 2+ members then ignore
  for free, with no special case.

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
