---
source: tests/test_vocatives.py
last_synced: 2026-09-17T18:23:32Z
source_hash: fc5143eb1f64eaaf8c4bb820bc24811a6f9ecc0d
---

## Purpose
Covers `ingest.vocatives.detect_narrator_aliases`: reading a narrator's several
names out of who says what to whom, with no model and no extraction. Every
fixture is shaped from a real measurement on a real book rather than invented -
the numbers each encodes live in
`context/src/bookrag/ingest/vocatives.py.md`.

## Public Interface
Eighteen tests plus `_I_NARRATE` / `_HE_NARRATES` narration fixtures and the
`_chapter` / `_said_by_another` / `_said_by_narrator` builders.

## Key Decisions
- **The narration fixtures are deliberately over-dense and over-length.**
  `_I_NARRATE` runs well above the 4.0-per-100-words first-person threshold and
  comfortably past the 50-word floor, so no test fails for a threshold reason
  it isn't about. `_HE_NARRATES` is the same sentences with third-person
  pronouns, so a first/third-person pair differs only in the thing under test.
- **`test_curly_single_quotes_are_found_too` earns its place twice.** It pins
  the quote-pair detection (a hardcoded pair returns zero spans *silently*,
  which reads as "this book has no dialogue"), and writing it is what caught a
  real recall bug: in `'Come along, boy,' he said` the comma sits inside the
  quotation marks, so the utterance ends with `,` and the trailing-vocative
  pattern originally accepted only `.?!`. That bug was losing vocatives on
  every book, not just single-quoted ones.
- **`..._a_third_person_chapter_inside_a_first_person_book_contributes_nothing`
  is the load-bearing safeguard**, not an edge case. The book that prompted all
  of this is a five-novel omnibus whose later sections switch narrator, and
  there "the boy" is a servant. The test asserts both that the first-person
  chapter still yields its alias and that the third-person chapter's vocative
  is absent, because passing only the first half would be satisfied by a
  detector that had stopped working.
- Tests assert on `dict(found.aliases)` rather than the ordered list wherever
  order is not the subject, so adding a name does not break an unrelated test.

- **`test_a_candidate_who_also_speaks_is_another_character`** pins the fix for
  the precision failure that the first measurement missed entirely: in a
  first-person novel the narrator overhears conversations he is not part of, so
  "spoken by someone other than the narrator" does not mean "addressed to the
  narrator". The fixture gives Trammel both an addressed line and two speaking
  lines, which is the real shape (`"Well, Trammel?" Brumbee asked`).

- **Three capitalisation tests close a gap this file had from the start.** The
  name/epithet split is the property that decides whether a candidate can be
  linked or reach question matching, and nothing here asserted any part of it -
  `reads_as_a_name` was only ever exercised in `test_alias_linking.py` on
  *hand-built* `AliasCandidate` objects, so the path from real chapter text
  through `_vocative_in_trailing_position` to `times_capitalised` was covered by
  exactly one CLI test.
  - `..._sorts_a_name_from_an_epithet_in_trailing_position` asserts the ratio on
    real detector output.
  - `..._a_vocative_introduced_by_you_or_my_is_still_the_same_sighting` is the
    sharp one. `", you thief."` and `", my boy."` are the two determiner forms
    the trailing pattern allows and nothing covered them, which made them the
    place where `_vocative` and `_vocative_in_trailing_position` could most
    easily disagree about *which word the vocative is*. Verified by sabotage:
    with a divergent second copy of the pattern this fails and nothing else in
    the suite does — the first sabotage attempt, against a fixture without a
    determiner, passed cleanly and proved the earlier test too weak.
  - `..._the_surface_form_the_book_used_is_what_gets_reported` pins that the
    reported name reads like the book ("Connwaer"), not a lowercased token,
    since that string ends up in `entities.json` as something a reader asks about.

- **Two chapter-evidence tests, and the second is the only end-to-end cover for
  the two-narrator bug.** `auto_link_plan` tells one addressee from another by
  comparing `AliasCandidate.chapters`, so that field has to be populated
  correctly from real chapter text.
  - `..._each_candidate_records_the_chapters_it_was_addressed_in` asserts the
    field directly, including that the to-narrator direction is the only one
    recorded.
  - `..._a_second_narrators_epithet_does_not_land_on_the_first` builds two
    first-person narrators in alternating chapters, the second called by a
    single name so she forms no qualifying group, and runs the whole
    detect → plan path. It asserts both that *both* narrators' vocatives are
    harvested (the pooling is real and unavoidable at detection time) and that
    only the first narrator's epithet survives the plan. This file is the only
    home for it: `test_alias_linking.py`'s version builds `AliasCandidate`s by
    hand and so cannot catch the detector failing to record chapters at all.

- **Three tests cover the capitalisation denominator and the one-vocative rule**
  (added 2026-09-17, see the module's context doc for the corpus measurements).
  All three assert against real detector output, which matters because the
  property they pin lives in a dataclass that `test_alias_linking.py` builds by
  hand — the exact shape that once let a fixture and production disagree.
  - `..._a_leading_sighting_does_not_dilute_the_capitalisation_ratio` is the
    bug. The fixture gives one trailing sighting and two leading ones, so the
    old denominator reads 2/6 and calls the narrator's own name an epithet
    while the new one reads 2/2. It asserts the old ratio explicitly
    (`times_capitalised < times_addressed * 0.8`) rather than only the verdict,
    so it still describes what was wrong if the threshold ever moves.
  - `..._a_vocative_never_seen_in_trailing_position_is_not_a_name` pins the
    fail-closed case the new denominator opens: `0 >= 0 * 0.8` is true, so a
    candidate with no capitalisation evidence would otherwise be promoted.
  - `..._a_leading_false_positive_never_outranks_the_real_trailing_vocative`
    pins behaviour that **looks like a bug and is not** — `_vocative` returns on
    a trailing match and never examines the leading one. Its fixtures
    ("Tea, boy," and "Where, boy?") are verbatim from the corpus, where all 19
    both-position utterances have a false-positive leading match. The test
    exists to stop the next reader "fixing" it.

## Dependencies
- Internal: `bookrag.ingest.vocatives`, `bookrag.ingest.chapter.Chapter`
- External: none (no pytest fixtures needed - the unit under test is pure)

## Open Questions / TODOs
- No test covers the known three-party failure (a speaker facing the narrator
  while addressing someone else, which harvested "captain" from the real book).
  It is documented in the source and in the module's context doc but not
  pinned, because pinning it would assert the *wrong* answer as expected
  behaviour. It should become a test the moment the behaviour is fixed.

## `_by_name` helper
`detect_narrator_aliases` now returns `AliasCandidate` objects rather than
`(name, count)` tuples, because auto-linking needs the surface form and the
capitalisation count. `_by_name(found)` lowercases back to `{name: count}` for
the tests that do not care; the ones that do assert on the dataclass directly.
