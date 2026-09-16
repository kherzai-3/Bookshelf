---
source: tests/test_vocatives.py
last_synced: 2026-09-16T19:53:59Z
source_hash: 4b213453ef5a13cdda0cf780d9f3a86187f2dab4
---

## Purpose
Covers `ingest.vocatives.detect_narrator_aliases`: reading a narrator's several
names out of who says what to whom, with no model and no extraction. Every
fixture is shaped from a real measurement on a real book rather than invented -
the numbers each encodes live in
`context/src/bookrag/ingest/vocatives.py.md`.

## Public Interface
Nine tests plus `_I_NARRATE` / `_HE_NARRATES` narration fixtures and the
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
