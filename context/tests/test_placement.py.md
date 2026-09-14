---
source: tests/test_placement.py
last_synced: 2026-09-13T20:30:00Z
source_hash: 2bb1823845a4af73597e26c339d4f0d25d06cd75
---

## Purpose
Covers GPU/CPU placement reporting end to end: `ModelPlacement`'s arithmetic,
the `model_placement(provider)` optional-capability probe,
`OllamaProvider.model_placement()` reading `/api/ps`, and the lines
`cli.placement_notes` actually shows a user. The failure being prevented is a
silently CPU-bound run, which looks exactly like a fast one until several hours
have passed.

## Public Interface
- `placement(size, vram, model=...)` — builds a `ModelPlacement`.
- `fake_ps(monkeypatch, payload, *, boom=False)` — stubs `urllib.request.urlopen`
  with an `/api/ps` response, or an unreachable server.
- `Stub` — a provider exposing only `model_placement()`, for the rendering tests.

## Key Decisions
- **The partial-offload case is stubbed, not measured, and deliberately so.**
  The development machine has an integrated AMD Radeon 840M, which Ollama does
  not support, so its real placement is always `size_vram = 0` — the 30%/70%
  split a user reported is unreproducible here. Pinning it with a synthetic
  `/api/ps` payload is the only way it gets covered at all.
- The CPU-only test uses this machine's real measured figure
  (`size_bytes = 5_062_566_870`, `vram_bytes = 0`) rather than a round number.
- `test_an_almost_complete_offload_counts_as_full` guards the `>= 0.99`
  threshold: runtimes report non-layer overhead outside VRAM, so demanding
  exactly 1.0 would warn on a perfectly healthy full offload.
- Three tests pin that "can't tell" stays silent rather than guessing CPU — a
  provider without the capability, one whose capability raises, and one
  returning the wrong type. A hosted provider legitimately has no local
  placement, and a local one has none before its model loads.
- `test_a_partial_offload_reports_the_percentage_and_why_it_matters` asserts on
  the phrase "gate every token", because the non-obvious half of the message is
  precisely that 70% on GPU is *not* 70% of GPU speed.

## Dependencies
- Internal: `bookrag.providers.base` (`ModelPlacement`, `model_placement`),
  `bookrag.providers.ollama_provider.OllamaProvider`, `bookrag.cli.placement_notes`.
- External: `pytest` (`monkeypatch`, `approx`). No network — the one module
  that would otherwise need a live Ollama is stubbed.

## Open Questions / TODOs
- Nothing here exercises a real partial offload. If this project ever runs on a
  machine with a supported GPU that only partly fits the model, confirming the
  reported percentage against `ollama ps` would be worth doing once.
