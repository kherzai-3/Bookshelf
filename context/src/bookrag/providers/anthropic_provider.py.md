---
source: src/bookrag/providers/anthropic_provider.py
last_synced: 2026-09-09T00:00:00Z
source_hash: c6e15d379d7f093a7f6dd25ad5aba1873bd30b27
---

## Purpose
The real Claude-backed `Provider` implementation: sends a chapter's text
plus the already-known entity names to Claude via the Anthropic API and
parses a JSON array of new/changed facts back.

## Public Interface
- `AnthropicProvider(model: str | None = None)` — `model` resolves as
  `model or $ANTHROPIC_MODEL or DEFAULT_MODEL`, same override pattern as
  `OllamaProvider`. Raises `RuntimeError` at construction if
  `ANTHROPIC_API_KEY` isn't set (checked after `.env` loading, now done in
  `providers/__init__.py`), so a misconfigured run fails immediately and
  clearly rather than on the first extraction call.
- `AnthropicProvider.extract_facts(chapter_text, known_entities, content_type="fiction",
  known_entity_types=None) -> list[ExtractedFact]` — `content_type` selects the prompt/taxonomy the
  same way as `OllamaProvider`, just without the schema-forcing (see Open
  Questions).
- `AnthropicProvider.answer_question(question, context, content_type="fiction") -> str`
  — shares the `_complete` helper with `extract_facts`, just swaps in
  `ANSWER_SYSTEM_PROMPTS[content_type]`/`build_answer_user_message`.

## Key Decisions
- `.env` loading moved to `providers/__init__.py` (no longer done here
  directly) so it also covers an `OllamaProvider`-only run - see that
  file's context doc for why.
- `ANTHROPIC_API_KEY` is this standalone program's own credential, unrelated
  to whatever authenticates a developer's Claude Code or Claude.ai access.
  Bedrock/Vertex access (rather than a direct Anthropic Console key) would
  need `anthropic.AnthropicBedrock`/`AnthropicVertex` instead of
  `anthropic.Anthropic` - not implemented here, since `OllamaProvider`
  covers the no-API-key case and is the practical default
  (`registry.DEFAULT_PROVIDER`). This class is kept for whenever a direct
  API/Bedrock/Vertex credential is available.
- Shares `EXTRACTION_SYSTEM_PROMPTS`/`build_user_message` (`prompts.py`) and
  `parse_facts` (`parsing.py`) with `OllamaProvider` - factored out so the
  eval harness compares providers on the same prompt, not incidentally
  different wording.

## Dependencies
- Internal: `bookrag.providers.parsing.parse_facts`,
  `bookrag.providers.prompts` (`EXTRACTION_SYSTEM_PROMPTS`,
  `ANSWER_SYSTEM_PROMPTS`, `build_user_message`, `build_answer_user_message`)
- External: `anthropic`, `python-dotenv`

## Open Questions / TODOs
- Still not tested against a real API call - no Anthropic credential
  (direct key, Bedrock, or Vertex) has been available while building this.
- Unlike `OllamaProvider`, this class does not force a structured-output
  schema - Claude's Messages API has a comparable mechanism (a forced
  single `tool_use` call with the desired `input_schema`, guaranteeing
  type/enum/required-field conformance the same way Ollama's `format`
  schema does), but adding it here was deliberately deferred: this
  provider is untested against a live API in this project at all, so
  speculatively building and tuning an unverifiable schema-forcing path
  isn't worth it until real credentials exist to validate it against.
