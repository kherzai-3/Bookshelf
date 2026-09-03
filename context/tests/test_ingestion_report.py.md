---
source: tests/test_ingestion_report.py
last_synced: 2026-09-02T00:00:00Z
source_hash: c2c72b432ef87c7adac514443ef4196744503699
---

## Purpose
Covers `cli.classify_ingestion` (chapter-bound vs. text-bound thresholding,
including the empty-list edge case) and `cli.write_ingestion_report`
(correct classification line, and the text-bound-only reassurance note
about cataloging/querying still working against fragment boundaries).
