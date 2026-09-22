---
source: tests/test_locate.py
last_synced: 2026-09-22T20:19:13Z
source_hash: dc3ded968bac691661c3a27b832936b70a45626d
---

## Purpose
Covers `bookrag.locate`: finding the passage a fact came from, and rendering
a location a reader can act on.

## Public Interface
25 tests in four groups — finding the passage, rendering the location,
reading the library, and the volume map.

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

- **The volume tests assert the renumbering, not just the name.** A
  citation reading "The Burning Bridge, chapter 48" would name the right
  book and a chapter number that appears in no copy of it, which is the
  failure mode a name-only assertion cannot see. One test does the
  arithmetic directly (`volume_at`), one does it through a real
  `save_book`/`cite` round trip.

## Dependencies
- Internal: `bookrag.locate`, `bookrag.ingest.chapter.Chapter`,
  `bookrag.query.Fact`, `bookrag.storage.save_book`
- External: `pytest`

## Open Questions / TODOs
- Nothing here exercises a *paraphrase* in the hardest sense — vocabulary
  substitution with no shared content words. That case is unmatchable by
  design and the module abstains, but no test states it, because a fixture
  for it would only assert that a hard case returns None.
