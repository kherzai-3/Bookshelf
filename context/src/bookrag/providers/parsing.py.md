---
source: src/bookrag/providers/parsing.py
last_synced: 2026-09-03T00:00:00Z
source_hash: 7e421c3fb17554f7a8d4e6862bc8d5c988d8642a
---

## Purpose
Shared, lenient parsing of a provider's raw text response into
`ExtractedFact`s - factored out of `anthropic_provider.py` when
`ollama_provider.py` needed the same logic, so every provider's output is
forgiven the same way rather than each provider reimplementing its own
parsing quirks. Also owns `extraction_response_schema()`, the JSON Schema
`OllamaProvider` passes to Ollama's structured-output `format` field, so the
schema can't drift from what this file's own normalization actually accepts.

## Public Interface
- `parse_facts(raw_text: str) -> list[ExtractedFact]` — strips markdown
  code fences, then parses JSON. An empty dict (`{}`) returns `[]` - the
  model correctly reporting nothing to extract, not a malformed fact (see
  Key Decisions). Otherwise, if the top-level value is a dict, unwraps a
  list found under `"facts"`/`"results"`/`"data"`/`"items"`, or treats the
  dict itself as a single fact object. Raises `ExtractionParseError` on
  invalid JSON, a non-list/dict top level, a fact object missing a
  required key, or an `entity_type` outside `ALLOWED_ENTITY_TYPES` and not
  a known alias. Silently drops (not raises) an individual fact whose
  `statement` is implausibly long or contains a suspicious embedded
  substring (see Key Decisions) or whose `category` isn't recognized (fed
  through `_normalize_category` instead of dropped).
- `ALLOWED_ENTITY_TYPES = {"character", "setting", "theme"}` — the fixed
  catalog entity kinds, matching the original brief.
- `_normalize_entity_type(raw_type: str) -> str` — case-insensitive; an
  allowed value passes through, a known alias (`_ENTITY_TYPE_ALIASES`)
  maps to its real type, anything else raises `ExtractionParseError`.
- `ALLOWED_CATEGORIES = {"personality", "appearance", "relationship",
  "status", "description", "development"}` — the six categories the
  extraction prompt asks for.
- `_normalize_category(raw_category: str) -> str` — case-insensitive; an
  allowed value passes through, anything else is folded into
  `"description"` rather than raising (see Key Decisions for why this is
  lenient where `_normalize_entity_type` is strict).
- `extraction_response_schema() -> dict` — the JSON Schema for Ollama's
  `format` field: `{"facts": [{"entity_name": str, "entity_type": enum,
  "category": enum, "statement": str (maxLength 300)}]}`, built from
  `ALLOWED_ENTITY_TYPES`/`ALLOWED_CATEGORIES`.

## Key Decisions
- **`{}` means zero facts, not one malformed fact.** Found while comparing
  `llama3.2:3b` against `qwen2.5:7b-instruct` on the same chapter (a
  table-of-contents page with no real character content): the smaller
  model hallucinated a fact anyway (twice, with two different wrong names
  across two runs), while the larger model correctly returned `{}` -
  better behavior that the parser was, at the time, rejecting as
  malformed (empty dict has no `entity_name` key). This is direct evidence
  a bigger model doesn't just produce fewer *wrong* facts, it can also
  correctly recognize "nothing here" rather than forcing an answer.
- The dict-unwrapping exists because a small local model (llama3.2:3b, via
  `OllamaProvider`) is more likely than Claude to wrap the requested array
  in an object - real behavior observed while testing, not speculative.
- Deliberately does NOT attempt to repair malformed JSON (e.g. a missing
  comma) - that's a rabbit hole. See `ollama_provider.py`'s
  `extraction_response_schema()` usage for the actual fix to that failure
  mode (constrain generation via a real JSON Schema in Ollama's `format`
  field, don't repair output after the fact).
- **`entity_type` is enforced against a fixed list, not just documented in
  the prompt** - this isn't only about tidiness: `resolve.py`'s
  `resolve_entity` matches an existing entity by `(name, type)` together,
  so if the same real entity gets a *different* type string across
  extraction runs, it silently fails to match itself and becomes a
  duplicate entity instead of being recognized as the one already known.
  Real case: a real run against `llama3.2:3b` produced `"monster"` and
  `"creature"` for real creatures (Kalkara, Wargal) instead of the
  requested enum. Known synonyms are folded via `_ENTITY_TYPE_ALIASES`
  (currently just `monster`/`creature` → `character` - both are non-human
  but still have personality/relationship/status facts, i.e. they're
  "characters" in the story sense); anything else is rejected
  (`ExtractionParseError`, counted like any other parse failure) rather
  than silently accepted as a new type or coerced to a guess - a
  genuinely new category becomes a visible decision (add an alias) instead
  of unbounded accumulation.
- **`category` is normalized leniently, unlike `entity_type`.** Nothing else
  keys off `category` for identity/dedup the way `resolve_entity` keys off
  `(name, type)`, so an unrecognized value is folded into `"description"`
  rather than rejecting the whole fact/chapter - never drop a chapter's
  worth of real facts over one mislabeled category. Real observed drift
  (before `extraction_response_schema()`'s enum existed): `"location"` and
  `"author"` both leaked through as category values.
- **A corrupted `statement` is dropped, not persisted.** Real observed case:
  one response tried to emit 4 facts, but used typographic curly quotes
  for the later ones' JSON keys/strings instead of a real closing `"` -
  `json.loads()` still succeeded (syntactically valid JSON), but 3 facts
  silently vanished into the first one's `statement`, which ended up
  containing literal `entity_name`/`entity_type` key text (curly-quoted,
  not straight-quoted - the check matches the bare key name so it catches
  either style). A `statement` over 500 chars or containing that text is
  dropped rather than persisted as garbage. Deliberately not surfaced as a
  returned count (unlike `parse_failure_count`/`ungrounded_entity_count` in
  `pipeline.py`) - see Open Questions.
- `extraction_response_schema()`'s `maxLength: 300` on `statement` is the
  primary defense against the corruption case above (a runaway string
  can't grow past that length, so it can't swallow subsequent facts); the
  drop-check above is a secondary net for providers/paths that don't use
  the schema (or if it's ever bypassed).

## Open Questions / TODOs
- The corrupted-statement drop has no visible count the way
  `parse_failure_count`/`ungrounded_entity_count` do in `pipeline.py` -
  `parse_facts`'s return type stays `list[ExtractedFact]` rather than
  threading a new value through both providers and every existing test.
  Disclosed tradeoff, not a silent omission - worth revisiting if this
  turns out to be a recurring problem rather than a rare edge case.

## Dependencies
- Internal: `bookrag.providers.base` (`ExtractedFact`, `ExtractionParseError`)
