---
source: tests/test_query.py
last_synced: 2026-09-13T16:40:00Z
source_hash: d42480d94e2cdf1e2970148e474534fe1e57fc42
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

Two areas added since:
- **Story-time rendering.** `test_format_context_separates_occurrences_from_
  standing_description` pins the split that makes the recency rule safe —
  `status`/`development`/`relationship` render as an ordered sequence of
  separate moments, `appearance`/`personality`/`description` as a single
  current state. `test_format_context_treats_every_nonfiction_category_as_
  standing` keeps that partition from misfiring on nonfiction, whose
  categories have no narrative present at all.
  `test_format_context_keeps_separate_entities_in_separate_blocks` guards the
  rendering boundary the split runs inside.
- **Statement-text matching**, for questions naming no entity at all:
  `..._matches_statement_text_when_no_entity_is_named`,
  `test_statement_matching_tolerates_a_reader_phrasing_that_is_not_the_books`,
  `test_statement_matching_ignores_words_common_across_the_book` (term rarity
  within the book, so "the"/"Halt" don't match everything), and
  `test_statement_matching_is_capped` (the cap that keeps a broad question
  from re-inflating context back to the whole catalog).
