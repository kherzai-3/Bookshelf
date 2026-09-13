---
source: tests/helpers.py
last_synced: 2026-09-13T16:40:00Z
source_hash: b9c411a0d4a202e24c4ccb934ee8d2167d768bd5
---

## Purpose
Shared synthetic epub/pdf builders, factored out so `test_epub_loader.py`,
`test_pdf_loader.py`, and `test_cli.py` don't each hand-roll their own sample
book. Both builders set title/author metadata so `extract_metadata` tests
have something real to assert against.

## Public Interface
- `build_sample_epub(path)` / `build_sample_pdf(path)` — two short (~3-word)
  chapters each; fine for ingest/metadata tests, too short to exercise real
  extraction (see `NARRATIVE_PADDING` below).
- `build_narrative_epub(path)` — like `build_sample_epub`, but with two
  chapters padded (via `_bulk_filler`) to ~725 words each, for tests that need
  extraction to actually run against real chapter text, not just ingestion.
  The size is set by `ingest.consolidate`, not by extraction: clearing
  `MIN_NARRATIVE_WORDS` (20) only takes a sentence or two, but anything near
  that would sit under `CONSOLIDATION_MEDIAN_WORDS_THRESHOLD` and get merged
  into a single chapter, breaking every test that assumes two.
- `_bulk_filler(min_words)` — private; repeats the same proper-noun-free,
  `FakeProvider`-safe padding until it clears `min_words`.
- `NARRATIVE_PADDING: str` — a ~20-word block of filler sentences to append
  to a short synthetic `Chapter.text` in extraction/query tests, so it
  clears `MIN_NARRATIVE_WORDS` without `FakeProvider` mistaking any of it
  for a new entity: every sentence starts with one of `FakeProvider`'s own
  pronoun stopwords (It/He/She/They/We), and no other word in it is
  capitalized.
- `build_fragmented_epub(path, fragment_count=40, words_per_fragment=100)` —
  many small, untitled, unheaded spine documents (no `h1`-`h3` markup at
  all), mirroring a real page-scanned Internet-Archive epub (Atomic
  Habits' actual source: one physical page per spine file) - for tests
  that need `ingest.consolidate.should_consolidate` to actually trigger.

## Key Decisions
- `NARRATIVE_PADDING` is appended, never prepended, to a test's real
  sentence(s) - `FakeProvider` splits per sentence and keeps each sentence's
  exact text as its `statement`, so appending preserves the original
  sentence (and any exact-string assertions on it) unchanged while still
  padding the chapter's total word count.
- `build_narrative_epub` exists as a separate builder rather than lengthening
  `build_sample_epub` itself, since the latter is shared by tests
  (`test_epub_loader.py` etc.) that assert its exact short content -
  lengthening it in place would have risked breaking those.
