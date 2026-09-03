---
source: tests/helpers.py
last_synced: 2026-09-03T00:00:00Z
source_hash: 552cbb3e4e131b1b372b4300163d6b7f72995b79
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
  chapter paragraphs (~20+ words each) long enough to clear
  `extract.pipeline.MIN_NARRATIVE_WORDS`, for tests that need extraction to
  actually run against real chapter text, not just ingestion.
- `NARRATIVE_PADDING: str` — a ~20-word block of filler sentences to append
  to a short synthetic `Chapter.text` in extraction/query tests, so it
  clears `MIN_NARRATIVE_WORDS` without `FakeProvider` mistaking any of it
  for a new entity: every sentence starts with one of `FakeProvider`'s own
  pronoun stopwords (It/He/She/They/We), and no other word in it is
  capitalized.

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
