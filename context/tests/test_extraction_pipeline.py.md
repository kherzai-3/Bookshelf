---
source: tests/test_extraction_pipeline.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 79632a6b5e5d55cf6eda7aa4fee01aa567008ac2
---

## Purpose
Covers `extract.pipeline.extract_book` end-to-end with `FakeProvider`:
correct `facts.jsonl` shape/chapter-scoping, `entities.json` updates, that a
series' second book seeds its known-entities context from the first book
(only genuinely new entities count toward `new_entity_count`), the
per-chapter `ExtractionParseError` tolerance regression (`_FailsOnNthCall`
test double) found running a real 75-chapter book, that `on_chapter_done`
fires once per chapter with `(1-indexed position, total)`, and the
new-entity grounding-check regression (`_FixedResponseProvider` test
double) found in the same real run.

Also covers resumable extraction (`resume_start_index` +
`extract_book(..., restart=)`): a simulated crash (`_FailsAfterNChapters`)
leaves `extraction_progress.json` correctly pointing at the first
un-processed chapter and a resumed call picks up there without
reprocessing earlier chapters; a `KeyboardInterrupt` propagates but still
leaves progress saved (same mechanism, not special-cased in
`extract_book`); a resumed run correctly treats an entity resolved in the
*interrupted* portion as already-known rather than wrongly re-grounding it
(`test_extract_book_resume_reuses_entities_from_the_interrupted_portion` -
this is the specific bug class this feature could have reintroduced if
`known_names` weren't reseeded to include `book_id` itself on resume);
`restart=True` ignores saved progress; a `chapter_count` mismatch (book was
re-ingested) is treated as stale and ignored; and an already-fully-extracted
book is a no-op (provider never called) unless `restart=True`.

Also covers the exact-duplicate-fact filter
(`test_extract_book_drops_exact_duplicate_facts_within_a_chapter`): a
`_FixedResponseProvider` response containing the same `(entity_name,
statement)` pair twice (once case-varied) is deduped to one fact before
being written, with `duplicate_fact_count` reporting how many were
dropped - the code-side guardrail added after a real chapter's real
extraction was found padding toward a raised `maxItems` cap by repeating
the same fact verbatim.
