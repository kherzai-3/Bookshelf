---
source: tests/test_library.py
last_synced: 2026-09-22T17:40:00Z
source_hash: 7a8087f706d19d9fb659ec4049ba49b294b193be
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

- **The residue rule** (`_residue_variant_pairs`, build-order 02c) — a
  decorated form of a name the book uses far more often on its own. Every
  fixture is built by `_book_mentioning`, which writes prose containing each
  name an exact number of times as a *maximal* capitalised run, because
  frequency in the book's own text is the rule's only evidence.

  **Every one of these tests uses two decorated forms, and that is not
  decoration.** With a single one, `_fuller_name_pairs` links it already on
  containment alone, so a two-entity fixture passes with the residue rule
  deleted - which is how these were first written and what a sabotage run
  caught. Two decorated forms trip that rule's ambiguity veto, and only the
  residue rule survives it. That is also the honest statement of what this
  rule adds at entity level: the multi-form case, plus frequency evidence in
  place of pure spelling.

  Linking: `..._treats_more_titles_as_more_evidence` (02c(ii) dissolving -
  four decorated forms of Fang Yuan as one cluster, where the old veto gave
  nothing; only `Lord` is in `_TITLES`, and the clan name `Gu Yue` could not
  be in a wordlist at all), `..._keeps_two_decorated_characters_apart` (two
  men of the same clan stay two clusters),
  `..._links_a_sentence_initial_word_to_the_bare_name` ("But Fang Yuan" -
  the 181-prefix-forms trap, where folding it in is the right answer).

  Refusing, one test per guard, each verified by deleting that guard alone:
  `..._refuses_a_family_name_shared_across_characters` (guard B - "Gu" sits
  inside longer names more often than it stands alone, and guard A cannot see
  it because the book never writes "gu" in lowercase),
  `..._refuses_a_capitalised_everyday_word` (guard A - "Chi Qu You", the
  capitalised-everyday-word failure it shares with the grounding check),
  `..._needs_the_bare_name_to_be_established` (the 100-sighting floor),
  `..._needs_the_bare_name_to_dominate` (the 5x ratio, pinned with the
  weakest real case in the corpus: "Qing Shu" 143 against "Gu Yue Qing Shu"
  129), `..._ignores_a_one_off_decorated_form` ("Demon King Fang Yuan", which
  occurs once in 2,360 chapters - and the surrounding cluster is still
  formed, so the hapax is excluded rather than allowed to suppress it),
  `..._splits_a_name_that_is_two_people_joined` (the conjunction guard looks
  only past the first token: "Tug And Blaze" is refused, "And Ryan" links),
  `..._leaves_a_qualified_category_noun_alone` (the characters-only
  restriction, which removes the entire measured error class).

- **Linking names** (`link_names`) —
  `test_link_names_before_extraction_stops_the_split_forming` is the important
  one and deliberately runs the *real* pipeline twice in one test: unseeded
  first, asserting the split actually forms, then seeded, asserting it does
  not. Asserting only the seeded half would pass against a detector that had
  quietly stopped working. `..._after_extraction_merges_what_is_already_there`
  covers the other direction (a real extraction costs hours, so arriving late
  must not mean starting over), and `..._refuses_a_single_name` the guard.

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
