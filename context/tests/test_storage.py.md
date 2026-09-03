---
source: tests/test_storage.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 68a397a643f81418a8f35f1a1b1544aa8e6f22f6
---

## Purpose
Covers `bookrag.storage`: slug generation, book-id collision handling, the
full `save_book` write (source copy + metadata.json + chapters.jsonl +
index.json update), and its rollback behavior on failure.

## Key Decisions
- `test_series_books_each_keep_their_own_chapter_2` is the load-bearing test
  for the series requirement: it ingests two books sharing a series with
  independently-numbered "chapter 2"s and asserts they land in separate
  `book_id` directories with distinct text, while both still show up grouped
  under the same series in `index.json`.
- `test_save_book_leaves_no_partial_directory_on_failure` monkeypatches
  `_update_index` to raise partway through `save_book` and asserts the
  `book_dir` it had already started writing is gone afterward.
