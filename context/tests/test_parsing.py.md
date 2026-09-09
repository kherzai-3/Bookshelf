---
source: tests/test_parsing.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 0014569d4255feab3586fba0a3dbaaf10e1b4b41
---

## Purpose
Covers `providers.parsing.parse_facts`: bare array, markdown-fenced array,
dict-wrapped list, single bare object, empty array, empty object (the
real `qwen2.5:7b-instruct` "nothing to extract" case), the
`ExtractionParseError` cases (invalid JSON, missing required field,
unrecognized `entity_type`), and `entity_type` normalization (allowed
values pass through, the real `monster`/`creature` → `character` alias
case, case-insensitivity). Also covers `extraction_response_schema()`'s
shape, including its `facts` array's `maxItems` cap (asserted at 40 - see
that function's own comment/context doc for why it was raised from the
original 25).
