---
source: tests/test_query.py
last_synced: 2026-09-09T00:00:00Z
source_hash: eaca361ae8be1ea6f127eb6cf87fdeaacc0ea3c0
---

## Purpose
The load-bearing test for the project's core promise: `facts_as_of` never
leaks a fact from beyond the given `(book_id, chapter_index)`. Covers a
standalone book (chapter-by-chapter filtering), a series book querying an
earlier chapter (all of an earlier series book counts as "in the past"),
and querying an *earlier* book in a series (a later book's facts must never
leak backwards). Also covers `format_context`'s rendering (entity-name
resolution, category/chapter grouping, empty input) and
`select_relevant_facts`'s matching (exact name, the real "Wargal" vs
"Wargals" plural-variant case via `match_key`, an alias match,
case-insensitivity, and the no-match-falls-back-to-everything guarantee).
