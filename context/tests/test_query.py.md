---
source: tests/test_query.py
last_synced: 2026-09-02T00:00:00Z
source_hash: cbd23eb5410421c150eb4a913e07e8af42e25781
---

## Purpose
The load-bearing test for the project's core promise: `facts_as_of` never
leaks a fact from beyond the given `(book_id, chapter_index)`. Covers a
standalone book (chapter-by-chapter filtering), a series book querying an
earlier chapter (all of an earlier series book counts as "in the past"),
and querying an *earlier* book in a series (a later book's facts must never
leak backwards).
