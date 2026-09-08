---
source: src/bookrag/providers/ollama_provider.py
last_synced: 2026-09-08T00:00:00Z
source_hash: dd84ef415adbcc5b713909101e92713dcccfc65f
---

## Purpose
Local, no-API-key `Provider` implementation via Ollama's REST API - the
practical default for this project, since the user's only Claude access is
enterprise SSO with no direct `ANTHROPIC_API_KEY`/Bedrock/Vertex path
confirmed. Verified against a real, locally-running `llama3.2:3b` model.

## Public Interface
- `OllamaProvider(model=None, base_url=None, num_ctx=DEFAULT_NUM_CTX,
  timeout=DEFAULT_TIMEOUT_SECONDS)` — `model` resolves as `model or
  $OLLAMA_MODEL or DEFAULT_MODEL` ("llama3.2:3b"); `base_url` similarly via
  `$OLLAMA_BASE_URL` then `"http://localhost:11434"`. `DEFAULT_NUM_CTX = 8192`,
  `DEFAULT_TIMEOUT_SECONDS = 900`. The env-var path is what makes switching
  to a bigger model on a different (e.g. GPU-equipped) machine a one-line
  `.env` change rather than a code edit - see README's "LLM provider setup".
- `OllamaProvider.extract_facts(chapter_text, known_entities, content_type="fiction") ->
  list[ExtractedFact]` — raises `RuntimeError` (not `ExtractionParseError`)
  if Ollama itself isn't reachable, doesn't respond within `timeout`, or a
  request that started responding stalls past `timeout` mid-read (both
  `urllib.error.URLError` and a bare `TimeoutError` are caught and
  re-raised the same way - see Key Decisions). `content_type` selects
  which schema/prompt pair (`EXTRACTION_SYSTEM_PROMPTS[content_type]`,
  `extraction_response_schema(content_type)`) and which `parse_facts`
  taxonomy get used.
- `OllamaProvider.answer_question(question, context, content_type="fiction") -> str`
  — shares the `_chat` helper with `extract_facts`, but with no
  `response_format`/`temperature` override, since a conversational answer
  is free text, not a structured fact list, and benefits from Ollama's
  normal sampling defaults. `content_type` only selects which prompt
  (`ANSWER_SYSTEM_PROMPTS[content_type]`) is used - the mechanism is
  identical either way.

## Key Decisions
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
- Sends `"options": {"num_ctx": 8192}` - raised from Ollama's default 4096
  tokens, which a long chapter (real chapters up to ~3865 words, roughly
  5000+ tokens with prompt overhead) can exceed.
- Sends `"temperature": DEFAULT_EXTRACTION_TEMPERATURE` (0.2) for
  `extract_facts` only - lower than Ollama's own default (~0.8), since
  extraction is a structured task that benefits from more deterministic
  sampling; `answer_question` leaves it unset, since a conversational
  answer benefits from the normal default instead.
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
- `_chat` takes `response_format`/`temperature` keywords (replacing the
  earlier boolean `json_format`) so it can back both methods: a schema +
  low temperature for `extract_facts`, neither for `answer_question`.

## Dependencies
- Internal: `bookrag.providers.parsing` (`parse_facts`,
  `extraction_response_schema`), `bookrag.providers.prompts`
  (`EXTRACTION_SYSTEM_PROMPTS`, `ANSWER_SYSTEM_PROMPTS`, `build_user_message`,
  `build_answer_user_message`)
- External: none beyond stdlib (`urllib`); requires Ollama itself running
  locally with the target model pulled (`ollama pull llama3.2:3b`)

## Open Questions / TODOs
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
