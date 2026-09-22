---
source: tests/test_locate.py
last_synced: 2026-09-22T23:30:00Z
source_hash: e2a505b3a09294c8ce5294fc269c442f5c2d2a46
---

## Purpose
Covers `bookrag.locate`: finding the passage a fact came from, and rendering
a location a reader can act on.

## Public Interface
21 tests in three groups — finding the passage, rendering the location, and
reading the library.

## Key Decisions
- **Two properties are guarded and only one is "does it find the passage".**
  The other is *does it refuse to guess*: a citation pointing at the wrong
  sentence tells a reader the book says something it does not, and they
  cannot tell that from a correct one. Both defects pinned here were found by
  running the matcher against real extractor output, not invented statements.
- **The fixture chapter deliberately repeats "Choosing Day"**, because IDF is
  computed over a chapter's own sentences. A short fixture where every term
  is unique makes common words look maximally rare and tests a scoring regime
  that never occurs in a real book — the first version did exactly that and
  disagreed with the measured result it was written to pin.
- **The fixture carries a decoy sentence** ("Horace examined the target he
  had been shooting at") holding every word of the real one except the name,
  placed first so ties resolve to it. Without it,
  `test_a_capitalised_stopword_is_read_as_a_name` passed with the name rule
  deleted — the generic words alone found the right sentence.
- **The two-sentence test asserts the quote spans both sentences.** The
  first version asserted only that a match was found, which a single-sentence
  match satisfied, so it passed with the pair window removed.
- Every guard is sabotage-verified: reverting `_UNSEEN_IDF` to 0, deleting
  the capitalised-stopword rule, not learning names from the chapter,
  removing the pair window, and letting a title outrank pages each fail
  exactly the tests that describe them.

## Dependencies
- Internal: `bookrag.locate`, `bookrag.ingest.chapter.Chapter`,
  `bookrag.query.Fact`, `bookrag.storage.save_book`
- External: `pytest`

## Open Questions / TODOs
- Nothing here exercises a *paraphrase* in the hardest sense — vocabulary
  substitution with no shared content words. That case is unmatchable by
  design and the module abstains, but no test states it, because a fixture
  for it would only assert that a hard case returns None.
