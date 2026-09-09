---
source: tests/test_extraction_pipeline.py
last_synced: 2026-09-09T00:00:00Z
source_hash: ec33e23a3bc312f29a0152a5121125c2187cee21
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
