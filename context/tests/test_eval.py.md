---
source: tests/test_eval.py
last_synced: 2026-09-23T00:00:00Z
source_hash: f2184c9c2592cbea4163320c90f5dce597db4623
---

## Purpose
Covers `eval.py`: `groundedness_score` on supported vs. unsupported
statements, `run_eval`'s read-only guarantee (no `facts.jsonl`/
`entities.json` written), parse-failure tracking via a local
`_AlwaysFailsProvider` test double, and `summarize`'s per-provider fact
counts.

## Multi-model comparison and the quality columns (added 2026-09-23)

- `test_run_eval_keeps_two_models_of_one_provider_apart` — the reason
  `run_eval`'s `providers` takes `(label, provider)` pairs rather than a dict.
  Two models of one provider share a provider name, so a dict silently keeps
  only the last, discarding the one comparison the command exists for. The
  dict form is still exercised by the older tests here, which is the
  backwards-compatibility guarantee.
- `test_run_eval_accumulates_known_entities_across_chapters` — that chapter 2's
  prompt is told what chapter 1 introduced, as `extract_book` does. Passes
  chapter indices out of order (`[1, 0]`) to also pin that they are run in
  ascending order, since accumulation is meaningless in any other order.
  `run_eval` used to pass `[]` every time, measuring a first-chapter prompt for
  every chapter - a condition no real run is ever in.
- `test_summarize_reports_the_quality_columns` — that the report carries
  distinct entities, citation coverage, near-duplicates and the fact ceiling,
  not just fact count and groundedness.
- `test_near_duplicate_pairs_catches_a_rephrasing_the_exact_dedup_misses` —
  built from two real statements a small model produced about the same event
  ("driven back into" / "exiled into" the same place, same year). Asserts the
  strings differ *first*, because that is the whole point: the pipeline's own
  exact-match dedup keeps both, and a fact count rewards the model for it.
- `test_citation_coverage_falls_when_a_model_paraphrases_off_the_text` — one
  statement drawn from the chapter's own words and one invented around it,
  asserting 50% coverage. This is the column that protects citations; nothing
  else in the suite would notice a model whose facts are fine but no longer
  traceable to a findable sentence.
- `_AlwaysFailsProvider` grew `known_entity_types` to match the real `Provider`
  protocol, because `run_eval` now passes it.
