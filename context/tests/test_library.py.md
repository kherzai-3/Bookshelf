---
source: tests/test_library.py
last_synced: 2026-09-15T16:05:24Z
source_hash: ab19455473a403340bd814f77a184ab330c88588
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

- **Name-variant detection** (`detect_name_variants`) — one person under
  several names, the thing that finally populates `aliases` from a book.
  Every case is taken from the real 493-entity library rather than invented:
  `..._finds_a_title_in_front_of_a_name` (Baron Arald / Arald),
  `..._offers_three_forms_of_one_name_as_a_single_decision` (Battlemaster
  David / Sir David / David - the union-find, so the user is asked once, not
  three overlapping times), `..._finds_a_given_name_and_a_fuller_form`.
  The false-positive tests are the load-bearing half, one per guard:
  `..._keeps_two_people_who_merely_share_a_rank_apart`,
  `..._refuses_a_given_name_two_people_share`,
  `..._ignores_a_name_that_is_two_entities_joined` (Tug and Blaze),
  `..._leaves_concepts_alone` (Finite Game / Game),
  `..._stays_silent_when_the_book_never_links_the_names`.
  `..._needs_the_book_to_state_a_prefix_link` covers the reported
  Conn/Connwaer case, and `test_merging_a_name_variant_makes_either_name_find_
  all_the_facts` is the end-to-end payoff: detect, merge, then confirm
  `select_relevant_facts` finds both entities' facts under either name.
  `test_doctor_reports_name_variants_without_touching_them` pins that `--fix`
  never merges.

## Key Decisions
- **Two of the false-positive tests were originally vacuous, and a sabotage
  run is what caught it.** The concepts test used only Finite/Infinite/Game
  and the rank test used only three kings - both *ambiguous* shapes, so the
  ambiguity veto rejected them and each test still passed with the guard it
  claimed to cover deleted. They now each carry an unambiguous pair
  (Temptation / Temptation Bundling; Battlemaster / Battlemaster David) where
  only the named guard stands between the pair and a merge. All five guards
  are sabotage-verified: removing any one fails exactly one test.
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
