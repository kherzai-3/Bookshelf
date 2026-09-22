---
source: tests/test_spoiler_safety.py
last_synced: 2026-09-22T23:30:00Z
source_hash: 5aacd97549ff56ad8db017dfeb7f857102661d57
---

## Purpose
The project's ship gate: proof that a render for a reader at chapter N cannot
contain, or be derived from, anything past chapter N. Deliberately separate
from `tests/test_query.py`, which unit-tests `facts_as_of` /
`select_relevant_facts` / `format_context` in isolation. This module runs the
whole real path a `bookrag chat` turn runs — `save_book` → `extract_book` →
`facts_as_of` → `select_relevant_facts` → `format_context` — because a leak is
far more often an *interaction* between those steps than a bug inside one of
them: a filter that is individually correct still leaks if the step after it
derives a value from what the filter removed.

## Public Interface
Four tests, plus module-level fixture material:
- `test_no_chapter_past_the_reading_position_reaches_the_render` — the
  sentinel test. Sweeps every reading position × all three retrieval tiers.
- `test_a_render_cannot_tell_a_truncated_library_from_a_full_one` — the
  equivalence test, parametrized over positions 0/1/4/8/9. **The actual gate.**
- `test_asking_about_a_character_who_has_not_appeared_yet_confirms_nothing`
- `test_a_later_book_in_the_series_changes_nothing_about_an_earlier_one`
- `_chapters(start, stop)`, `_build_library`, `_render`, `_source` — helpers.

## Key Decisions
- **The two flagship tests fail for different reasons, and that is the point.**
  The sentinel test *names* the leak (a token unique to chapter i, so a failure
  says which chapter escaped into which render). The equivalence test needs no
  idea of what a leak looks like — it renders chapter N from the full book and
  from a library that never held anything past N, and demands byte-identity.
  That catches the kinds a sentinel cannot: a count in a header, a rarity score
  computed over hidden facts, an entity ordering that shifts once a later
  chapter exists, a bucket boundary that moves.
- **Sabotage-verified, and the two sabotages separate the two tests:**
  1. An off-by-one in `facts_as_of` (`> limit` → `> limit + 1`) fails the
     sentinel test *and* the equivalence test at every position below the last.
  2. Prepending a count derived from the whole-book entity registry to
     `format_context`'s output — a derived-value leak that copies no text —
     leaves the sentinel test **passing** and fails equivalence at every
     position. This is the concrete demonstration that equivalence is the
     stronger gate, not a duplicate of the sentinel test.
- **Separate library roots for the equivalence test**, so each library has its
  own `entities.json`. The global registry is the most plausible back channel:
  it is written by the full extraction and then read at render time by both
  `select_relevant_facts` (aliases, canonical names) and `format_context`
  (id → name). A shared root would test nothing.
- **`_render` mirrors `cli.py`'s chat loop exactly** (`facts_as_of` →
  `select_relevant_facts` → `format_context`), in one place, so these tests
  cannot drift into guarding a path the product doesn't take.
- **Non-vacuity is asserted explicitly.** An empty render satisfies every leak
  assertion, so each render is asserted non-empty, and for the two questions
  guaranteed to include the reading position's own chapter, that chapter's
  sentinel is asserted *present*. Without this a regression that returned `""`
  would read as a clean pass.
- **One question per retrieval tier** (`_QUESTIONS`): a named entity, a
  statement-text match, and a broad question that matches nothing and falls
  back to every fact. Each tier reaches `format_context` with a
  differently-derived set, so each is a separate chance to leak; the third
  produces the largest render and is the likeliest carrier of a stray line.
  `_INCLUSIVE_QUESTIONS` drops the topical one, which past chapter 7 correctly
  narrows to the quarry and so need not contain the current chapter.
- **Sentinels are purely alphabetic** (`Sentinelalfa`, not `Sentinel0`):
  `FakeProvider`'s proper-noun regex is `\b[A-Z][a-z]+\b`, which a digit suffix
  defeats, so a numbered sentinel would never be extracted as an entity and the
  test would pass vacuously.
- **Maren recurs in every chapter and shares each sentence with that chapter's
  sentinel.** That is not scene-setting: a statement is stored whole, so her
  facts are the realistic carrier of a leak — a future name riding along inside
  a fact about someone the reader already knows.
- `_chapters(start, stop)` always re-indexes from 0. Handing `save_book` a book
  whose chapters begin at index 5 would be testing a shape the product never
  produces.

- **`_render` is the definition of "what a reader sees", and adding a render
  surface means adding it there.** That is the only way the two flagship
  tests ever reach a new surface. Citations were added to it for exactly this
  reason, and they are a sharper leak risk than anything before them: a fact
  statement is a paraphrase that might omit a spoiler, but a citation quotes
  the book's own text verbatim.
- Sabotage-verified on the citation path specifically. Quoting chapter N+1
  fails the sentinel *and* equivalence tests; adding a whole-book-derived
  chapter count to a citation ("Chapter Four of 10") copies no future text at
  all and fails **equivalence only** - a live demonstration of the case the
  sentinel test structurally cannot see, on a surface added months after that
  argument was first made.

## Dependencies
- Internal: `bookrag.storage.save_book`, `bookrag.extract.pipeline.extract_book`,
  `bookrag.ingest.chapter.Chapter`, `bookrag.providers.fake_provider`,
  `bookrag.query` (all three primitives), `tests.helpers.NARRATIVE_PADDING`
- External: `pytest` (`parametrize`)

## Open Questions / TODOs
- Rank 10 (book-level fields: cast, antagonist, plotline) is gated on this
  module existing. When those land they add a new render surface, and the
  equivalence test must be extended to cover it — a cast list rendered at
  chapter 3 that names the chapter-60 villain is precisely the leak this
  module exists to stop, and equivalence only guards what it is pointed at.
- The renders here are assembled by `FakeProvider`'s deterministic extraction.
  That is correct for a leak test (the question is what the *pipeline* passes
  through, not what a model writes), but it means no real model's output shape
  is exercised.
