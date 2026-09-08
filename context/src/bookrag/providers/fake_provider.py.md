---
source: src/bookrag/providers/fake_provider.py
last_synced: 2026-09-08T00:00:00Z
source_hash: 6b1936ef59dc9c128d5bf35807b5ad83b7a93463
---

## Purpose
Deterministic, no-network `Provider` implementation - the only reason the
extraction pipeline, eval harness, and CLI can all be tested without an
`ANTHROPIC_API_KEY`.

## Public Interface
- `FakeProvider.extract_facts(chapter_text, known_entities, content_type="fiction") ->
  list[ExtractedFact]` — one fact per new capitalized word (regex
  `[A-Z][a-z]+`, excluding a small stopword set) in the chapter, with the
  sentence it appeared in as the `statement`. `entity_type` is always
  `"character"`, `category` always `"development"`, regardless of
  `content_type` (accepted, ignored - see Key Decisions).
- `FakeProvider.answer_question(question, context, content_type="fiction") -> str`
  — deterministic stand-in for the real providers' `answer_question`:
  returns the "not enough information" message verbatim when `context` is
  blank, otherwise `f"[fake answer] Based on: {context}"`. `content_type`
  likewise accepted and ignored.

## Key Decisions
- Deliberately dumb and predictable, not a good extractor - it exists to
  make output assertable in tests (`tests/test_fake_provider.py`), not to
  approximate real extraction quality. `known_entities` and `content_type`
  are both accepted (for `Provider` protocol compatibility) but currently
  ignored. Note `category="development"` is fiction-only (not a member of
  `ALLOWED_CATEGORIES_NONFICTION`, see `providers/parsing.py`) - harmless
  here since this class constructs `ExtractedFact` directly and never goes
  through `parse_facts`/`_normalize_category`'s validation, but a reminder
  that this double makes no attempt to model nonfiction output
  realistically regardless of what `content_type` is passed.

## Dependencies
- None beyond stdlib (`re`).
