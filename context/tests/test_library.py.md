---
source: tests/test_library.py
last_synced: 2026-09-13T16:40:00Z
source_hash: f1b7cdfe4f262b2832f595f7a24cdfa43c9cecf3
---

## Purpose
Covers `bookrag.library`'s actual list/show/remove/doctor logic (as opposed
to `test_cli.py`'s coverage of the CLI plumbing around it): the
`chapters_extracted`/`partial` completion heuristic (including the real
Ranger's Apprentice case that motivated using `max(chapter_index) + 1`
rather than a distinct-chapter count - see `library.py`'s context doc),
orphaned-index-entry detection, `remove_book`'s entity-pruning-vs-deleting
distinction (shared entity kept with the book_id removed vs. an
now-bookless entity deleted outright), and `run_doctor`'s three original
independent checks plus its report/`--fix` split.

Also covers `detect_duplicate_entities` (a real-shaped cluster spanning
name variants *and* entity_types unifies, without false-positives across
genuinely different names; `run_doctor --fix` leaves detected clusters
untouched) and `merge_entities` (facts rewritten to the kept entity across
potentially multiple book directories, `aliases` populated from every
merged-away entity's own name/aliases, `book_ids` unioned, defaulting
`keep` to the most-facts entity, and the `ValueError` cases: fewer than
two real entity_ids, or a `keep` that isn't one of them).

Also covers two areas added since:
- **Facts pointing at an unregistered entity**
  (`test_run_doctor_reports_a_fact_pointing_at_an_unregistered_entity`,
  `test_doctor_fix_never_deletes_facts_with_an_unregistered_entity`) — doctor
  reports it, and `--fix` deliberately will not resolve it by deleting facts.
  Extracted facts are the expensive artifact (hours of real model time);
  registry entries are cheap to rebuild.
- **Cross-book entity detection and splitting** — the repair for entities
  wrongly shared between unrelated books before identity was series-scoped:
  `test_doctor_detects_an_entity_shared_by_unrelated_books`,
  `test_doctor_does_not_flag_an_entity_shared_within_one_series` (the
  legitimate case must not be flagged),
  `test_split_gives_each_book_its_own_entity_and_rewrites_its_facts`,
  `test_split_drops_a_book_reference_with_no_facts_behind_it`, and
  `test_split_preserves_every_fact` — the load-bearing one, since a split
  rewrites fact rows across multiple book directories and must not lose any.

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
