---
source: src/bookrag/providers/base.py
last_synced: 2026-09-03T00:00:00Z
source_hash: fc835059662d2fe4dc7307f0a261893ac9d42125
---

## Purpose
Shared types every provider (`AnthropicProvider`, `OllamaProvider`,
`FakeProvider`) implements against - the contract the extraction pipeline
and `cli.py`'s `chat` command both depend on, not any one provider's
specifics.

## Public Interface
- `ExtractedFact(entity_name: str, entity_type: str, category: str,
  statement: str)` — one raw fact as returned by a provider, before entity
  resolution assigns it a stable `entity_id` (see `extract.resolve`).
- `ExtractionParseError` — raised when a provider's raw output can't be
  parsed into facts; `eval.py` catches this to score schema-conformance
  rather than letting the whole run crash.
- `Provider` (Protocol) — `extract_facts(chapter_text: str, known_entities:
  list[str]) -> list[ExtractedFact]`; `answer_question(question: str,
  context: str) -> str` — answers a reader's question from spoiler-safe
  facts only (see `prompts.ANSWER_SYSTEM_PROMPT`).

## Key Decisions
- `Provider` is a `typing.Protocol`, not an ABC — providers don't need to
  inherit from anything, they just need the right method shape (matches
  `FakeProvider`, which is a plain class with no base class).
