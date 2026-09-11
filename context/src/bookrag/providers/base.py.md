---
source: src/bookrag/providers/base.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 8c7f06fb27cf1a7157bb8c26a710db5df813f051
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
  list[str], content_type: str = "fiction", known_entity_types: dict[str,
  str] | None = None) -> list[ExtractedFact]`; `answer_question(question:
  str, context: str, content_type: str = "fiction") -> str` — answers a
  reader's question from spoiler-safe facts only (see
  `prompts.ANSWER_SYSTEM_PROMPTS`). `content_type` selects which
  category/entity-type taxonomy and which prompt pair a provider uses
  (`"fiction"` or `"nonfiction"`) - defaults to `"fiction"` so every caller
  written before this existed keeps working unchanged. `known_entity_types`
  (name -> already-established entity_type) is optional, purely a prompt-
  building hint (see `prompts.build_user_message`) - not used by the
  grounding/resolution logic in `extract.pipeline`, which keeps using the
  plain `known_entities` list unchanged.

## Key Decisions
- `Provider` is a `typing.Protocol`, not an ABC — providers don't need to
  inherit from anything, they just need the right method shape (matches
  `FakeProvider`, which is a plain class with no base class).

## Story time on `ExtractedFact` (`when`, `time_phrase`)
`when` ∈ `{"present", "past", "future"}` records where a fact sits in *story*
time, as distinct from the chapter that revealed it. Both fields default
(`"present"`, `None`), so every fact extracted before they existed remains
valid and reads as present-tense - which it overwhelmingly is.

The distinction is load-bearing, not decorative: `chapter_index` is the
*discourse* position and alone governs spoiler safety, while `when` says when
the thing actually happened, which may be long before the book opens. Real
case it exists for: `[ch 4] "King Duncan, a youth in his twenties, was newly
crowned when Morgarath rebelled"` was stored indistinguishably from something
happening in chapter 4, so "how old is the King?" answered "a youth in his
twenties" via the recency rule. He would be about forty.

`time_phrase` holds the text's own wording ("fifteen years earlier") copied
verbatim, and is displayed but never parsed - see `parsing.py`'s context doc.
