---
source: src/bookrag/providers/base.py
last_synced: 2026-09-08T00:00:00Z
source_hash: 886cc94d8f20ad39eff111e576de354582cdcd4b
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
  `entity_type` is fiction's `"character"|"setting"|"theme"` or
  nonfiction's `"character"|"concept"|"theme"`, depending on which
  taxonomy produced it (see `providers/parsing.py`).
- `ExtractionParseError` — raised when a provider's raw output can't be
  parsed into facts; `eval.py` catches this to score schema-conformance
  rather than letting the whole run crash.
- `Provider` (Protocol) — `extract_facts(chapter_text: str, known_entities:
  list[str], content_type: str = "fiction") -> list[ExtractedFact]`;
  `answer_question(question: str, context: str, content_type: str =
  "fiction") -> str` — answers a reader's question from spoiler-safe facts
  only (see `prompts.ANSWER_SYSTEM_PROMPTS`). `content_type` selects which
  category/entity-type taxonomy and which prompt pair a provider uses
  (`"fiction"` or `"nonfiction"`) - defaults to `"fiction"` so every caller
  written before this existed keeps working unchanged.

## Key Decisions
- `Provider` is a `typing.Protocol`, not an ABC — providers don't need to
  inherit from anything, they just need the right method shape (matches
  `FakeProvider`, which is a plain class with no base class).
