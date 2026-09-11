---
source: src/bookrag/providers/parsing.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 136f64e07f0f38a77d6548c743ed44033e339051
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
- `parse_facts(raw_text: str, content_type: str = "fiction") -> list[ExtractedFact]`
  — strips markdown code fences, then parses JSON. An empty dict (`{}`)
  returns `[]` - the model correctly reporting nothing to extract, not a
  malformed fact (see Key Decisions). Otherwise, if the top-level value is
  a dict, unwraps a list found under `"facts"`/`"results"`/`"data"`/
  `"items"`, or treats the dict itself as a single fact object. Raises
  `ExtractionParseError` on invalid JSON, a non-list/dict top level, a fact
  object missing a required key, or an `entity_type` outside the allowed
  set for `content_type` and not a known alias. Silently drops (not
  raises) an individual fact whose `statement` is implausibly long or
  contains a suspicious embedded substring (see Key Decisions) or whose
  `category` isn't recognized (fed through `_normalize_category` instead
  of dropped).
- `ALLOWED_ENTITY_TYPES = {"character", "setting", "theme"}` — the fiction
  catalog entity kinds, matching the original brief.
- `ALLOWED_ENTITY_TYPES_NONFICTION = {"character", "concept", "theme"}` —
  drops `setting` entirely, adds `concept` (a named, citable framework/
  technique the book teaches as a discrete unit).
- `_normalize_entity_type(raw_type: str, content_type: str = "fiction") -> str`
  — case-insensitive; an allowed value (for the given `content_type`)
  passes through, a known alias (`_ENTITY_TYPE_ALIASES`/
  `_ENTITY_TYPE_ALIASES_NONFICTION`, selected the same way) maps to its
  real type, anything else raises `ExtractionParseError`.
- `ALLOWED_CATEGORIES = {"personality", "appearance", "relationship",
  "status", "description", "development"}` — the six fiction categories
  the extraction prompt asks for.
- `ALLOWED_CATEGORIES_NONFICTION = {"definition", "claim", "technique",
  "example", "relationship", "description"}` — a parallel, not shared,
  taxonomy (see Key Decisions for why a shared/parameterized one wasn't
  used).
- `_normalize_category(raw_category: str, content_type: str = "fiction") -> str`
  — case-insensitive; an allowed value (for the given `content_type`)
  passes through, anything else is folded into `"description"` rather than
  raising (see Key Decisions for why this is lenient where
  `_normalize_entity_type` is strict). `"description"` is a member of both
  taxonomies, so the fallback is always valid regardless of `content_type`.
- `extraction_response_schema(content_type: str = "fiction") -> dict` — the
  JSON Schema for Ollama's `format` field: `{"facts": [{"entity_name": str,
  "entity_type": enum, "category": enum, "statement": str (maxLength
  300)}]}` (`facts` itself capped at `maxItems: 40`), built from the
  `ALLOWED_ENTITY_TYPES*`/`ALLOWED_CATEGORIES*` pair selected by
  `content_type`.

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
- **`facts`'s `maxItems: 25` fixes a real runaway-generation failure, not a
  hypothetical one.** Diagnosed via Ollama's own `server.log`: one real
  extraction request generated 8,490+ output tokens (normal chapters
  produce 500-1500) over 14m43s, running with the *correct* `n_ctx_slot =
  8192` the whole time (ruling out a context-size misconfiguration as the
  cause), before Ollama's internal server hit its own limit, returned a
  500, and restarted the model subprocess. From the client side this
  looked like a hang (near-zero CPU over a short sample window - misleading,
  since ~9.7 tokens/sec of real generation is easy to miss in an 8-second
  sample), but it was actually still working the entire time, just never
  satisfying the grammar's condition to close the array. An open-ended
  array under grammar-constrained decoding has no structural reason to
  ever terminate if the model doesn't confidently choose to - `maxItems`
  makes "keep going forever" impossible rather than merely unlikely.
  Verified empirically that Ollama's grammar conversion actually honors
  `maxItems` (tested with a deliberately open-ended prompt against a
  `maxItems: 3` schema - the model was forced to stop at exactly 3 items),
  and re-verified the production schema against the real chapter that had
  previously been the highest-volume one seen (32 facts uncapped) - it now
  completes in ~90s with a natural `done_reason: stop`, not truncation.
  Originally set to 25 from real observed data (the richest chapter seen at
  the time produced 32, itself thought to be an outlier). **Raised to 40**
  after a full real 75-chapter extraction (Ranger's Apprentice) showed the
  opposite problem: 12 of the last ~20 chapters landed at exactly 25 total
  facts - real evidence the cap was routinely binding, not just guarding
  against an outlier. Still a hard, finite ceiling, not a return to
  uncapped.
- **The nonfiction taxonomy is a separate set, not a parameterized version
  of the fiction one** - confirmed necessary, not just theoretically
  different, by a real checkpoint run (`bookrag eval` against consolidated
  Atomic Habits chapters, see `extract/pipeline.py`'s context doc for how
  `content_type` gets there): the fiction categories collapsed almost
  everything into `"description"` (a real named thing, "Habits Academy",
  got the exact same generic treatment as an abstract idea), and
  `"setting"` produced outright nonsense - "desk", "phone", "bedroom",
  "coffee shop" all filed as cataloged story settings, when they were just
  illustrative examples in a discussion of habit cues. `setting` is
  dropped entirely for nonfiction for this reason; `"technique"` (a
  concrete, actionable instruction) is the one category with no fiction
  analog - it's what lets a reader later ask "what techniques does this
  book recommend?" separately from "what does it claim?". `"relationship"`
  is reused but redefined: concept-to-concept (builds on/is a component
  of), not person-to-person. No aliases seeded for
  `_ENTITY_TYPE_ALIASES_NONFICTION` (unlike fiction's monster/creature) -
  grown from real observed drift if/when it happens, not guessed upfront.
  `definition` vs `claim` has acknowledged soft edges for a small model
  (the same *kind* of risk as the fiction category drift above) -
  deliberately not resolved further until more real extraction data shows
  how bad it actually is.

## Open Questions / TODOs
- The corrupted-statement drop has no visible count the way
  `parse_failure_count`/`ungrounded_entity_count` do in `pipeline.py` -
  `parse_facts`'s return type stays `list[ExtractedFact]` rather than
  threading a new value through both providers and every existing test.
  Disclosed tradeoff, not a silent omission - worth revisiting if this
  turns out to be a recurring problem rather than a rare edge case.

## Dependencies
- Internal: `bookrag.providers.base` (`ExtractedFact`, `ExtractionParseError`)

## Occurrence vs standing categories (added with the conflation fix)
- `OCCURRENCE_CATEGORIES = {"status", "development", "relationship"}` /
  `OCCURRENCE_CATEGORIES_NONFICTION = set()` /
  `OCCURRENCE_CATEGORIES_BY_CONTENT_TYPE` — which categories describe a
  distinct *moment* rather than a standing property. Consumed by
  `query.format_context` to decide which facts render as a chronological
  sequence (where a later fact never supersedes an earlier one) and which
  keep the per-category, later-wins grouping.
- Why it exists: a real confirmed wrong answer. A ch.34 wound and an
  unrelated ch.66 death report - both `status` - were fused by the answer
  prompt's blanket recency rule into "he died fighting the monsters."
  Recency is correct for a rank/age/location (one current value) and wrong
  for occurrences, which simply both happened.
- Membership reasoning: `development` is unambiguous (the extraction prompt
  defines it as a notable action or event). `status` is defined there as a
  *change* in role/rank/life-condition, so it's an occurrence by
  construction - and it is the category the real bug occurred in.
  `relationship` is genuinely mixed ("Halt is Will's master" is standing;
  "Halt has sworn to rescue Will" is a moment) and is grouped with
  occurrences deliberately: mislabelling a standing fact as a moment only
  makes an answer more verbose, while mislabelling a moment as standing
  reintroduces the bug. Asymmetric blast radius decides it; worth revisiting
  against real answers.
- Nonfiction's set is empty **by design, not omission** - a definition,
  claim or technique is a standing statement, and even `example` doesn't get
  harmfully superseded by recency the way a story occurrence does.

## `ALLOWED_WHEN` / `time_phrase` (story-time fields)
- `ALLOWED_WHEN = {"present", "past", "future"}`, `DEFAULT_WHEN = "present"`,
  `_WHEN_ALIASES`, `_MAX_TIME_PHRASE_LENGTH = 80`.
- **Three coarse values, deliberately not a date or a global ordering.** A
  model reading one chapter at a time can tell whether a sentence is set in
  that chapter's present; it cannot place events on a book-wide timeline, and
  most novels give no dates to place them with. Asking for more than it can
  know invites invention.
- `when` is **required** in the schema (so grammar-constrained decoding forces
  exactly one enum token per fact); `time_phrase` is deliberately **optional**,
  because most chapters state no explicit time and requiring the field would
  push the model to make one up.
- `_normalize_when` folds an unrecognized value to the default rather than
  rejecting the fact - same posture as `category`, and unlike `entity_type`
  which gates identity and so rejects on drift. The aliases exist for
  providers that aren't schema-constrained (Anthropic, Fake).
- `time_phrase` is stored verbatim and **never parsed into a date**.
  Normalizing "fifteen years earlier" would invent precision the source
  doesn't have, and a later chapter's more precise phrasing would leak that
  precision to an earlier reader.
