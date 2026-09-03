---
source: tests/test_cli.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 8f36a2a45342797321d7f042e0a5dc4ebbf19d9a
---

## Purpose
End-to-end coverage of `bookrag.cli.main`: `ingest` (happy path, series
flags, missing file, unsupported extension, a corrupt file failing cleanly
rather than crashing, the ingestion report being written, and the
incoming-folder auto-delete behavior) plus `extract`/`eval` against
`--provider(s) fake` so no API key is needed, including the per-chapter
progress lines `extract` prints and that `--model` is threaded through to
`get_provider` (verified via a monkeypatched stand-in, not a real call).

## Key Decisions
- The `_library_root` autouse fixture points `BOOKRAG_LIBRARY_ROOT` at a
  `tmp_path` for every test in this module, so nothing here ever touches the
  real `data/library/`.
