---
source: tests/test_parsing.py
last_synced: 2026-09-13T16:40:00Z
source_hash: d0b1ded705fc2e3217b7508506919b8fb2d2d1ed
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

Also covers two areas added since:
- **Statement sanitization**: `test_corrupted_statement_is_dropped_not_
  persisted` and `test_overlong_statement_is_dropped` — a bad statement drops
  that one fact rather than failing the whole chapter's parse.
- **The nonfiction taxonomy**, which is a genuinely separate enum set rather
  than a superset: `..._nonfiction_uses_the_nonfiction_taxonomy` (schema),
  `..._accepts_a_nonfiction_category_and_type`,
  `..._rejects_a_fiction_only_entity_type` (so `setting` cannot leak into a
  nonfiction book), and `..._normalizes_an_unrecognized_category_leniently`
  (category drift is folded into a default, unlike `entity_type`, which gates
  identity and is rejected outright).
