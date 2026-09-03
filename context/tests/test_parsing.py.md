---
source: tests/test_parsing.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 93822f6373b890bc166c42a79a3348d25348c7bb
---

## Purpose
Covers `providers.parsing.parse_facts`: bare array, markdown-fenced array,
dict-wrapped list, single bare object, empty array, empty object (the
real `qwen2.5:7b-instruct` "nothing to extract" case), the
`ExtractionParseError` cases (invalid JSON, missing required field,
unrecognized `entity_type`), and `entity_type` normalization (allowed
values pass through, the real `monster`/`creature` → `character` alias
case, case-insensitivity).
