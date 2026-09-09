---
source: tests/test_library.py
last_synced: 2026-09-09T00:00:00Z
source_hash: ebeb272998a483e65c8da3685782c21f3397c21b
---

## Purpose
Covers `bookrag.library`'s actual list/show/remove/doctor logic (as opposed
to `test_cli.py`'s coverage of the CLI plumbing around it): the
`chapters_extracted`/`partial` completion heuristic (including the real
Ranger's Apprentice case that motivated using `max(chapter_index) + 1`
rather than a distinct-chapter count - see `library.py`'s context doc),
orphaned-index-entry detection, `remove_book`'s entity-pruning-vs-deleting
distinction (shared entity kept with the book_id removed vs. an
now-bookless entity deleted outright), and `run_doctor`'s three independent
checks plus its report/`--fix` split.

## Key Decisions
- Book fixtures are built via the real `storage.save_book` (`_make_book`
  helper), not hand-written `metadata.json` - same posture as
  `test_extraction_pipeline.py`. `facts.jsonl`/`entities.json` content is
  hand-written directly (`_write_facts`, `save_entities`) rather than run
  through a real provider, since these tests are about how `library.py`
  *reads* that state, not about producing it realistically.
- Uses `shutil.rmtree` on a just-created book directory to simulate the
  "orphaned index entry" state (a directory deleted outside the CLI) -
  matches how this state actually arose for real during earlier project
  work, rather than constructing `index.json` by hand.
