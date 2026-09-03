---
source: tests/test_extraction_pipeline.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 48cf333cc7106745b243a1f59dfcb4f74dce9861
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
