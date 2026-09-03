---
source: src/bookrag/providers/fake_provider.py
last_synced: 2026-09-03T00:00:00Z
source_hash: 50d99fd34bd948d3be497e7a6c68850ff9070cf7
---

## Purpose
Deterministic, no-network `Provider` implementation - the only reason the
extraction pipeline, eval harness, and CLI can all be tested without an
`ANTHROPIC_API_KEY`.

## Public Interface
- `FakeProvider.extract_facts(chapter_text, known_entities) ->
  list[ExtractedFact]` — one fact per new capitalized word (regex
  `[A-Z][a-z]+`, excluding a small stopword set) in the chapter, with the
  sentence it appeared in as the `statement`. `entity_type` is always
  `"character"`, `category` always `"development"`.
- `FakeProvider.answer_question(question, context) -> str` — deterministic
  stand-in for the real providers' `answer_question`: returns the
  "not enough information" message verbatim when `context` is blank,
  otherwise `f"[fake answer] Based on: {context}"`.

## Key Decisions
- Deliberately dumb and predictable, not a good extractor - it exists to
  make output assertable in tests (`tests/test_fake_provider.py`), not to
  approximate real extraction quality. `known_entities` is accepted (for
  interface compatibility) but currently ignored.

## Dependencies
- None beyond stdlib (`re`).
