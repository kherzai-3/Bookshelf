---
source: src/bookrag/eval.py
last_synced: 2026-09-08T00:00:00Z
source_hash: b53747cc16dc77f87556ac5615c7d96d1d9c5ad0
---

## Purpose
Read-only harness for judging/comparing provider output on the same
chapters - never writes to the real `facts.jsonl`/`entities.json`, so it's
safe to run against production data without disturbing it.

## Public Interface
- `ProviderChapterResult(provider_name, chapter_index, facts, parse_ok)`
- `run_eval(book_id, chapter_indices, providers: dict[str, Provider], root=None)
  -> list[ProviderChapterResult]` — runs each provider independently per
  chapter (no shared `known_entities`, unlike the real pipeline - this is
  deliberately isolated per chapter for a fair comparison). Looks up the
  book's `content_type` via `storage.load_metadata(...).get("content_type",
  "fiction")` once, passed to every `extract_facts` call - real use: the
  checkpoint that validated the nonfiction taxonomy design was exactly a
  `run_eval` call (via `bookrag eval`) against consolidated Atomic Habits
  chapters, using the *then-current* fiction taxonomy to surface how badly
  it misfit before the nonfiction one was built.
- `groundedness_score(chapter_text: str, fact: ExtractedFact) -> float` —
  cheap lexical check in `[0.0, 1.0]`: fraction of the statement's
  significant (>3 char) words that literally appear in the chapter text.
  Not a semantic judge - a fast, deterministic sanity signal.
- `summarize(results, chapters: dict[int, Chapter], sample_count=2) ->
  list[str]` — per-provider aggregate (fact count, parse failures, average
  groundedness) plus a few sample statements per chapter, for human review.

## Key Decisions
- Framed as **groundedness**, not cross-provider "quality" - meaningful
  with a single provider configured, and doesn't require a second provider
  or a hand-labeled ground-truth dataset to produce a real number.
- A provider raising `ExtractionParseError` for a chapter is recorded as
  `parse_ok=False` with an empty fact list, not a crash - `summarize`
  reports the failure count so a badly-behaving provider is visible in the
  report rather than aborting the whole eval run.
- Combines the two things the user asked for explicitly: a side-by-side
  human-readable report AND an automated score, in the same output rather
  than as separate commands.

## Dependencies
- Internal: `bookrag.ingest.chapter.Chapter`, `bookrag.providers.base`,
  `bookrag.storage` (`library_root`, `load_chapters`, `load_metadata`)
