---
source: src/bookrag/eval.py
last_synced: 2026-09-23T00:00:00Z
source_hash: 911e81b43065e25d2becb20a7aa26d1a7647dc42
---

## Purpose
Read-only harness for judging/comparing provider output on the same
chapters - never writes to the real `facts.jsonl`/`entities.json`, so it's
safe to run against production data without disturbing it.

Its job is to answer "which model should extract this library?" in one
command. That is harder than it sounds, because the obvious metrics are the
misleading ones - see **Key Decisions**.

## Public Interface
- `ProviderChapterResult(provider_name, chapter_index, facts, parse_ok,
  seconds=None, usage=None)` — one model's result for one chapter. `seconds`
  and `usage` are `None` whenever the provider can't report them (Anthropic,
  the fakes) or the call failed; readers must treat `None` as "unknown",
  never as zero.
- `ProviderSummary(...)` — one model's scorecard across every chapter, with a
  `citation_coverage` property (`quoted / facts`).
- `run_eval(book_id, chapter_indices, providers, root=None)
  -> list[ProviderChapterResult]`. `providers` is a list of
  `(label, provider)` pairs; a `dict` is still accepted for the existing
  callers.
- `summarize_results(results, chapters, content_type="fiction", sample_count=2)
  -> list[ProviderSummary]` — the structured scorecard.
- `summarize(results, chapters, sample_count=2, content_type="fiction")
  -> list[str]` — the human-readable report built from it.
- `groundedness_score(chapter_text, fact) -> float` — fraction of the
  statement's >3-char words that literally appear in the chapter.
- `near_duplicate_pairs(facts) -> int` — pairs of statements in one chapter
  that say the same thing.
- `max_facts_per_chapter(content_type="fiction") -> int` — the schema's own
  `maxItems`, read from `extraction_response_schema` rather than duplicated.

## Key Decisions

**`providers` is a list of pairs, not a dict, because a dict cannot express
the comparison this command exists for.** Two models of one provider share a
provider name, so keyed by that name one silently overwrites the other. The
dict form is still accepted - every pre-existing caller passed one - but
`cli.py` builds pairs labelled `provider:model`.

**The columns were chosen from a real measured comparison that the old ones
got backwards.** On six chapters of a real book, `llama3.2:3b` beat
`qwen2.5:7b-instruct` on both things `summarize` used to report - twice the
facts, 18% faster - while being clearly worse:

| | qwen2.5:7b-instruct | llama3.2:3b |
|---|---|---|
| facts | 94 | 195 |
| distinct entities | 25 | **16** |
| near-duplicate pairs | 4 | **53** |
| chapters at the 40-fact ceiling | 0 of 6 | **3 of 6** |
| groundedness | 0.884 | 0.851 |
| citation coverage | 77% | 75% |

It was padding: on one chapter it produced exactly 40 facts about a *single*
entity, missing three others the same 970 words introduce. So the report now
carries `distinct_entities`, `near_duplicate_pairs`, `cap_hits` and
`citation_coverage` alongside the fact count, and every one of them is cheap
and deterministic - none needs a second model as a judge.

**`citation_coverage` is the column that protects citations.** A model that
paraphrases further from the prose than another costs `locate.find_passage`
its match, and the facts still look perfectly good while quietly ceasing to be
traceable to a sentence a reader can find. It came out level between these two
models (77% vs 75%) but swung from 100% to 57% between individual chapters, so
it needs watching rather than assuming.

**`near_duplicate_pairs` uses a crude content-word Jaccard at 0.6, on purpose.**
It is a ranking signal between models, not a dedup rule that decides any fact's
fate, so being roughly right about many pairs beats being exactly right about
few. It catches what the pipeline's own exact-match dedup structurally cannot:
"was driven back into the Mountains of Rain and Night fifteen years ago" and
"was exiled to the Mountains of Rain and Night fifteen years ago" are not equal
strings, so both survive, and a fact *count* rewards the model for producing
them.

**`run_eval` accumulates `known_entities` across chapters and runs them in
ascending order.** It used to pass `[]` every time, which measures a
first-chapter prompt for every chapter - a condition no real run is ever in
(measured: the preamble reaches 780 characters by chapter 8 of a real book and
keeps growing). Accumulation is kept *per provider*, so one model's entity
discoveries never leak into another's prompt and skew the comparison.

**Cost is reported as seconds as well as tokens, and the seconds are the
honest number.** Ollama reuses a cached KV prefix across calls that share one
and still reports the full token count: measured, an identical 1,439-token
system prompt took 34.23s on the first call and 0.12s on the second. Reporting
only `prompt_tokens` invites exactly the wrong conclusion about what a prompt
costs. See `providers/base.CallUsage`.

**`_total` propagates `None` rather than coercing to 0**, so a provider that
cannot report tokens shows a blank column instead of a confident "0 tokens".

## Dependencies
- Internal: `ingest.chapter`, `locate.find_passage`, `providers.base`
  (`CallUsage`, `ExtractedFact`, `ExtractionParseError`, `Provider`,
  `last_usage`), `providers.parsing.extraction_response_schema`,
  `storage` (`library_root`, `load_chapters`, `load_metadata`)
- External: none (stdlib only)

## Data Contracts
In: a book_id, chapter indices, and `(label, provider)` pairs.
Out: `ProviderChapterResult` per (model, chapter); `ProviderSummary` per model;
report lines from `summarize`. Nothing is written to disk.

## Open Questions / TODOs
- `near_duplicate_pairs` is O(n^2) in a chapter's facts. Fine at the schema's
  40-fact ceiling; would need revisiting if that cap ever rose a lot.
- The report is text. A machine-readable `--json` output would make
  model comparisons diffable across runs, which is what the throwaway
  scratchpad scripts did by hand.
