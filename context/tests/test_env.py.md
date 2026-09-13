---
source: tests/test_env.py
last_synced: 2026-09-13T15:24:02Z
source_hash: e9adaed86dde32c2b714231009fdf74abad3ff5f
---

## Purpose
Covers `bookrag.env`'s "blank means unset" rule and, most importantly, the
end-to-end regression it was written for: copying `.env.example` to `.env`
verbatim — what README instructs and what `install.py` does automatically —
must leave every default intact.

## Public Interface
- `blank_settings_in_env_example()` — helper; returns every `SOME_VAR=` name
  declared with an empty value in the repo's `.env.example`.
- Unit tests for `env_str`/`env_int`: unset, blank, whitespace-only, stripping,
  a real value, integer parsing, and the named-variable error on a non-numeric
  value.
- `test_the_documented_setup_path_leaves_every_default_intact` — the flagship:
  sets every blank `.env.example` setting to `""` and asserts `OllamaProvider`
  and `get_provider()` still resolve to their documented defaults.

## Key Decisions
- **The flagship test reads `.env.example` rather than hardcoding a list**, so
  a newly added optional setting is covered the moment it is added. That is the
  whole point — the original bug was a setting nobody thought to test blank.
- `test_env_example_declares_blank_settings` guards it: if `.env.example`'s
  format ever changes so the regex matches nothing, the flagship test would
  silently pass over an empty list. This asserts it found at least five.
- Sabotage-verified: with `env_str`/`env_int` reverted to the naive
  `os.environ.get(name, default)`, 8 of these tests fail.

## Dependencies
- Internal: `bookrag.env`, `bookrag.providers.ollama_provider`,
  `bookrag.providers.registry`, and the repo's own `.env.example`.
- External: `pytest` (`monkeypatch`).

## Open Questions / TODOs
- Only the Ollama provider is asserted end to end; `AnthropicProvider` can't be
  constructed without a real key, so its `ANTHROPIC_MODEL` blank-value path is
  covered only at the `env_str` level.
