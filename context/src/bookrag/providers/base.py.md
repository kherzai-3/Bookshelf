---
source: src/bookrag/providers/base.py
last_synced: 2026-09-13T19:30:00Z
source_hash: 782f9de70b0e810c70e12a2a09949cebf61ae456
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

## `extraction_identity(provider) -> str | None` (optional capability)

Returns `"<provider>:<model>"` (`"ollama:qwen2.5:7b-instruct"`,
`"anthropic:claude-sonnet-5"`, `"fake"`) for a provider that offers one, and
`None` for one that doesn't. Recorded in `extraction_progress.json` so a
resumed extraction can refuse to continue a different model's work - see
`extract/pipeline.py`'s `ExtractionResumeMismatch`.

**Deliberately a free function probing an optional method, not a member of
the `Provider` protocol.** Providers are matched structurally, and the test
suite passes many minimal stand-ins implementing `extract_facts` and nothing
else; making identity mandatory would break all of them to serve a
bookkeeping concern. A provider whose identity probe *raises* is treated
exactly like one that has none - an identity exists to label a run and must
never be what takes one down.

Callers must read `None` as **"unknown, so unverifiable"**, never as "a
different model".

## `ModelPlacement` / `model_placement(provider)` (optional capability)
Where a loaded model is resident: `model`, `size_bytes`, `vram_bytes`, plus
`gpu_fraction`, `is_cpu_only`, and `is_fully_on_gpu`. Probed exactly like
`extraction_identity` above and for the same two reasons - the many minimal
test stand-ins implement `extract_facts` and nothing else, and a *diagnostic*
must never be the thing that takes a run down (a capability that raises is
treated as absent).

- `is_fully_on_gpu` is `>= 0.99`, not `== 1.0`: runtimes report a little
  non-layer overhead outside VRAM, so an effectively-complete offload lands a
  shade under, and flagging that would cry wolf on the good case.
- `None` means "can't tell", never "CPU". A hosted provider has no local
  placement to report, and a local one cannot answer before its model is
  loaded.
- bookrag never *chooses* GPU or CPU - Ollama does, when it weighs free VRAM
  against the model plus its KV cache. This type exists only to report that
  choice, because a silently CPU-bound run looks identical to a fast one until
  hours have passed.
