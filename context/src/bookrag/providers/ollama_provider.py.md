---
source: src/bookrag/providers/ollama_provider.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 57dc5686a23d77ef2791bceadcb0b97c93699927
---

## Purpose
Local, no-API-key `Provider` implementation via Ollama's REST API - the
practical default for this project, since it requires no
`ANTHROPIC_API_KEY`/Bedrock/Vertex credential at all. Verified against real,
locally-running `llama3.2:3b` and `qwen2.5:7b-instruct` models.

## Public Interface
- `OllamaProvider(model=None, base_url=None, num_ctx=None,
  timeout=DEFAULT_TIMEOUT_SECONDS)` — `model` resolves TWO independent
  attributes, not one: `self._model` (extraction) as `model or $OLLAMA_MODEL
  or DEFAULT_MODEL` ("qwen2.5:7b-instruct"), and `self._answer_model` (chat
  answering) as `model or $OLLAMA_ANSWER_MODEL or DEFAULT_ANSWER_MODEL`
  (also "qwen2.5:7b-instruct" today - see Key Decisions for why these are
  separate constants despite the same current value). A single `model`
  override feeds both, which is harmless in practice since no caller uses
  both methods on the same instance. `base_url` similarly via
  `$OLLAMA_BASE_URL` then `"http://localhost:11434"`; `num_ctx` the same
  way via `$OLLAMA_NUM_CTX` then `DEFAULT_NUM_CTX` (16384 - see Key
  Decisions for why this was raised from 8192). `DEFAULT_TIMEOUT_SECONDS =
  900`. The env-var path is what makes switching models (or context window
  size) on a different machine a one-line `.env` change rather than a code
  edit - see README's "LLM provider setup".
- `OllamaProvider.extract_facts(chapter_text, known_entities, content_type="fiction",
  known_entity_types=None) -> list[ExtractedFact]` — raises `RuntimeError` (not `ExtractionParseError`)
  if Ollama itself isn't reachable, doesn't respond within `timeout`, or a
  request that started responding stalls past `timeout` mid-read (both
  `urllib.error.URLError` and a bare `TimeoutError` are caught and
  re-raised the same way - see Key Decisions). `content_type` selects
  which schema/prompt pair (`EXTRACTION_SYSTEM_PROMPTS[content_type]`,
  `extraction_response_schema(content_type)`) and which `parse_facts`
  taxonomy get used. Uses `self._model`.
- `OllamaProvider.answer_question(question, context, content_type="fiction") -> str`
  — shares the `_chat` helper with `extract_facts`, but with no
  `response_format`/`temperature` override, since a conversational answer
  is free text, not a structured fact list, and benefits from Ollama's
  normal sampling defaults (a temperature override was tried and reverted -
  see Key Decisions/Open Questions - so this output is still not fully
  reproducible run-to-run, unlike extraction). `content_type` only selects
  which prompt (`ANSWER_SYSTEM_PROMPTS[content_type]`) is used. Uses
  `self._answer_model`, passed explicitly to `_chat` (which now takes a
  `model` keyword, defaulting to `self._model` when omitted -
  `extract_facts`'s call doesn't pass it and gets `self._model` as before).

## Key Decisions
- **`DEFAULT_MODEL` changed from `"llama3.2:3b"` to `"qwen2.5:7b-instruct"`,
  and chat answering got its own independent `DEFAULT_ANSWER_MODEL`
  constant (same value today, but not derived from `DEFAULT_MODEL`).** Real,
  controlled comparison on this project's own data (same real chapter, same
  machine): `llama3.2:3b` showed genuine run-to-run non-determinism at
  `DEFAULT_EXTRACTION_TEMPERATURE` - one run on the chapter that reveals a
  character's appearance produced zero facts about that character at all,
  an identical second run produced a solid appearance fact for them.
  `qwen2.5:7b-instruct` was consistently precise across repeated runs on
  the same chapter AND was not slower (63s vs 78s measured) - it generates
  fewer, more targeted facts rather than padding output, so wall-clock time
  isn't simply proportional to parameter count. The two constants are kept
  separate (not one shared default) because a chat answer is a single
  cheap one-shot call (~1-2s measured either way) with none of extraction's
  hours-long cost pressure, so there's no reason to force the same
  size/speed tradeoff onto both - `$OLLAMA_ANSWER_MODEL`/`--model` on
  `bookrag chat` can move independently of extraction's choice later
  without any code change.
- Sends a real JSON Schema (`parsing.extraction_response_schema()`) as
  `/api/chat`'s `format` field for extraction, not just the string `"json"`
  - verified empirically against this project's local Ollama (0.33.2) to
  hold `enum` constraints even adversarially (asked it to classify a sword
  as character/setting/theme; it still picked one of the three rather than
  breaking the enum). This structurally prevents `entity_type`/`category`
  drift and, via the schema's `maxLength` on `statement`, caps a runaway
  string before it can swallow subsequent facts (a real, observed
  corruption case - see `parsing.py`'s context doc). `format: "json"`
  (kept as historical context: the original fix for `llama3.2:3b`
  producing syntactically invalid JSON) only ever guaranteed *some* valid
  JSON, not this schema - `parsing.parse_facts` still unwraps dict-wrapped
  lists leniently as a fallback for providers/paths that don't schema-
  constrain (Anthropic, Fake, or Ollama's `answer_question` path).
- Sends `"options": {"num_ctx": self._num_ctx}` (default 16384, was 8192
  until a second, larger overflow was found and fixed): the *original*
  8192 was itself already raised from Ollama's default 4096, which a long
  chapter (real chapters up to ~3865 words, roughly 5000+ tokens with
  prompt overhead) can exceed - that reasoning covers `extract_facts`'
  single-chapter calls. But `answer_question` sends a very differently-
  sized payload - `query.format_context`'s *entire* assembled context for
  the book so far, which has no size cap of its own by design (see that
  module's docstring) - and a real full-length novel's context measured at
  ~26,000-30,000 tokens by its final chapters, 3-4x even the 8192 window,
  meaning `bookrag chat` was silently overflowing on every call for a book
  that size. `query.select_relevant_facts` (added alongside this) is the
  real, scalable fix - only relevant facts are sent at all, keeping
  context size roughly independent of book length - `num_ctx` is a safety
  net for whatever still reaches the model after that filtering (e.g. a
  broad question naming no specific entity, which still gets everything).
- Sends `"temperature": DEFAULT_EXTRACTION_TEMPERATURE` (0.2) for
  `extract_facts` only - lower than Ollama's own default (~0.8), since
  extraction is a structured task that benefits from more deterministic
  sampling; `answer_question` leaves it unset, since a conversational
  answer benefits from the normal default instead.
- **A `temperature` override for `answer_question` was tried and reverted
  - a real cautionary tale about small-sample verification, not just a
  dead end.** Motivation was real: the answer prompt's cross-category
  instruction (see `prompts.py`'s context doc - reading a fact filed under
  the "wrong" category, like a beard mention filed under `personality`, to
  answer an appearance question) only worked some of the time against the
  real, unmodified `ranger-s-apprentice-1-2-bindup` facts.jsonl. An initial
  small sample (n=6 identical real questions) at temperature 0.4 landed
  6/6, versus roughly half at 0.0, 0.2, 0.6, and the default - looked like
  a real, if non-monotonic, effect. But re-running the same comparison
  with a larger, fairer sample (n=10 each) found 0.4 at 6/10 and the
  default at 7/10 - statistically indistinguishable, meaning the original
  6/6 was a lucky draw, not a genuine effect. Reverted rather than shipped
  on the strength of the small sample - see Open Questions for what this
  means for actually fixing the underlying inconsistency.
- `timeout` defaults to 900s (up from 300s, itself up from an initial 120s).
  Direct timing against a single real chapter (2000-2400 words) with the
  schema-constrained request measured 50-70s, comparable to the old
  `format: "json"` path - schema constraints don't meaningfully slow
  per-token generation on their own. But the prompt rewrite (dropping the
  unenforceable "only new/changed" instruction, adding per-category
  definitions and a worked example) makes the model far more thorough:
  a real isolated 75-chapter run registered 31 entities by chapter 10 alone
  (versus 18 *total* across the entire book under the old prompt), and
  individual chapter latency climbed accordingly (some chapters past #10
  exceeded 300s) as `known_entities` grew faster and each response had more
  facts to generate. This is a genuine quality/throughput tradeoff, not a
  transient issue - confirmed by reproducing it in complete isolation
  (nothing else touching the same Ollama instance). 900s is a deliberately
  generous margin accepted in exchange for keeping the richer extraction;
  see Open Questions for the capped-`known_entities` alternative that was
  considered and deferred instead.
- Uses stdlib `urllib.request` for the one JSON POST rather than adding an
  HTTP client dependency (`httpx`/`requests`).
- Shares `EXTRACTION_SYSTEM_PROMPT`/`build_user_message`/`parse_facts` with
  `AnthropicProvider` - same reasoning as noted there.
- No streaming (`"stream": False`) - simpler response handling; extraction
  isn't interactive/latency-sensitive enough to need it.
- `_chat` takes `model`/`response_format`/`temperature` keywords (the
  latter two replacing the earlier boolean `json_format`) so it can back
  both methods with their own independent choices: a schema + 0.2
  temperature + extraction model for `extract_facts`, no schema + the
  default temperature + answer model for `answer_question` (the
  `temperature` keyword exists for `answer_question` to use too, but
  nothing currently passes one for it - see Key Decisions' reverted
  attempt).

## Dependencies
- Internal: `bookrag.providers.parsing` (`parse_facts`,
  `extraction_response_schema`), `bookrag.providers.prompts`
  (`EXTRACTION_SYSTEM_PROMPTS`, `ANSWER_SYSTEM_PROMPTS`, `build_user_message`,
  `build_answer_user_message`)
- External: none beyond stdlib (`urllib`); requires Ollama itself running
  locally with the target model pulled (`ollama pull qwen2.5:7b-instruct`)

## Open Questions / TODOs
- The underlying inconsistency that motivated the reverted temperature
  experiment (see Key Decisions) is still real and still unfixed:
  `answer_question`'s cross-category recall (see `prompts.py`'s context
  doc) succeeds roughly half the time against the real, unmodified
  `ranger-s-apprentice-1-2-bindup` facts.jsonl, regardless of temperature
  in the 0.0-0.8 range tested (0.0 was the one clear exception - worse,
  not better). Temperature isn't the lever for this specific behavior;
  candidates not yet tried: self-consistency (ask the same question
  N times, e.g. via majority vote or having the model reconcile multiple
  draws - real added latency/cost per question, though still cheap in
  absolute terms given how fast one answer call is), or restructuring
  `query.format_context`'s rendering to surface loosely-related facts from
  other categories more saliently instead of leaving cross-referencing
  entirely to the model's own initiative.
- A genuinely new, unrelated problem surfaced while spot-checking 0.4 for
  answer coherence (not caused by this change, and not fixed here): the
  answer prompt's "trust the later chapter" conflict-resolution rule
  misapplied across two *different real events*, not just an updated
  status for the same event - asked "what happened to Halt during the
  fight with the Kalkara?" (a real ch.33-36 event), the model pulled in an
  unrelated ch.66 fact ("killed in the attempt to stop the Skandians" - a
  separate battle entirely) and concluded Halt died fighting the Kalkara,
  which isn't what happened. The rule currently has no way to tell "this
  status changed" apart from "this is a completely different occurrence
  that happens to share a category and entity." Not investigated further
  or fixed - flagged here for a future pass.
- CPU-only inference on this hardware (no NVIDIA GPU) measured at roughly
  8-15s per chapter for short chapters; longer chapters (~2000-4000 words)
  take proportionally longer, and now more so than before the extraction
  prompt rewrite (see Key Decisions) - a full-length novel's `bookrag
  extract` can now plausibly take well over an hour, not "tens of minutes."
  Real-time progress is surfaced by `cli.py`'s `on_chapter_done` callback,
  which requires this module's caller to flush output per chapter (see
  `pipeline.py`) since Python fully buffers stdout and file writes when not
  connected to a real terminal.
- Capping `known_entities`'s length (e.g. only the N most recent, or most
  relevant to the current chapter) was considered as a way to bound prompt
  growth and keep latency flatter across a long book, but deferred - it
  risks reintroducing name-consistency drift (the reason that list exists
  at all) and wasn't the timeout's sole cause (output volume per chapter
  matters at least as much as prompt length). Raising the timeout was
  chosen instead as the lower-risk fix for this pass.
