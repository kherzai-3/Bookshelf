---
source: src/bookrag/locate.py
last_synced: 2026-09-22T23:30:00Z
source_hash: e4f0eb919c0f4cca5f4545c8e5e2e346a6eaf709
---

## Purpose
Turns a fact into a place a reader can go and look. A fact carries
`(book_id, chapter_index)`, which is enough to store it and not nearly enough
to cite it — "chapter 34" is unfindable in a stitched omnibus, meaningless in
a book whose "chapters" this project invented by merging fragments, and
unhelpful at its best because a chapter is 2,000–3,000 words. This module
answers "where did this come from" in the reader's terms, from whatever
evidence the book actually has.

## Public Interface
- `Passage` — `quote`, `start` (char offset), `score`, plus
  `position_in_chapter(text)`.
- `Citation` — `book_title`, `volume`, `chapter_index`, `chapter_title`,
  `pages`, `passage`, `position`; `where()` renders the structural half and
  `render()` the whole thing.
- `cite(book_id, chapter_index, statement, root=None) -> Citation | None`
- `cite_facts(facts, root=None) -> list[tuple[Fact, Citation]]` — a whole
  answer's worth, reading each chapter once.
- `find_passage(statement, chapter_text) -> Passage | None`
- `names_in(text) -> frozenset[str]` — stopwords this text uses as proper
  nouns.
- `_MIN_PASSAGE_SCORE`, `_UNSEEN_IDF`, `_PAIR_PENALTY`, `_MAX_QUOTE_CHARS`.

## Key Decisions
- **The deliverable is a rendered location, not a storage layout.** What the
  database keys a chapter as is irrelevant; what matters is that the reader
  is told something they can act on. This is the correction that re-scoped
  the whole item — rank 04's omnibus split was ranked as a *precondition* for
  citations on the theory that per-book storage was required, and it was not.
  A display-label map over the same volume spans would have produced the same
  string.
- **The quote is the primary locator; the structural label is context.**
  Every structural label is edition-dependent — a page belongs to one scan, a
  chapter number to one printing. A sentence belongs to the book, and a
  reader can search for it in any reader or edition. This is what makes a
  scanned page number safe to show even though it can sit a few pages off the
  printed folio.
- **The ladder is `pages` → `chapter_title` → `chapter N`.** Pages outrank a
  title because of a real book: every chapter of *Finite and Infinite Games*
  has a title and all of them are meaningless PDF bookmark IDs ("FAIG0080"),
  so a title-only citation would look informative and be useless.
- **A wrong quote is worse than no quote**, so the matcher abstains. A
  citation that points at a passage not supporting what the reader was told
  reads as the tool being wrong about the *book*. Nine of 49 real statements
  get no quote and only a structural location; that is the designed
  degradation, not a failure.
- **Scoring is weighted recall of the statement's words, not similarity.**
  The statement is short and the source sentence may be long; penalising a
  sentence for words the statement omitted would prefer terse sentences over
  the right one. IDF is computed over the chapter's own sentences, so a name
  used once outweighs a word the chapter leans on — which adapts per book
  with no wordlist to maintain.
- **Two defects were found by measuring against real extractor output, and
  neither was visible from invented examples.** They compounded into the
  worst possible failure: a *perfect 1.00* score on a wrong passage.
  - `will` is a stopword and `Will` is the protagonist. Discarding it left
    "Will had not had a 'growing spurt' before Choosing Day" to be scored on
    "choosing" and "day" alone.
  - Words absent from the chapter were dropped from the **denominator** as
    well as the numerator, so a statement was scored only on what it happened
    to share with the book. "Baron Arald was the Lord of Redmont Fief" matched
    a sentence containing none of Arald, Lord, Redmont or Fief at 0.95.
    Unseen words are the strongest evidence a passage is *not* the source;
    they now weigh the maximum (`_UNSEEN_IDF = 1.0`).
- **Names are learned from the chapter and applied to the statement**, which
  is the only ordering that works. Capitalisation is the evidence and a
  statement supplies almost none: an extractor writes "Will was small and
  wiry", putting the name in the one position where a capital is free. The
  chapter says it a dozen times mid-sentence. Same
  read-the-book's-own-prose move as `names.person_link_groups` and
  `pipeline._entity_is_grounded`.
- **Sentence pairs are scored too**, with a small penalty so a single
  sentence wins a tie. A fact routinely restates two adjacent sentences as
  one, and a quote covering half the evidence points at half the evidence.
- **`_read_chapter` reads line by line** rather than loading
  `chapters.jsonl`: a citation needs one chapter and the largest book in the
  corpus is 2,360 of them. It also makes the spoiler property visible in the
  code — the function cannot return a chapter other than the one asked for.

## Measurement
49 statements from two Ranger's Apprentice chapters, produced by the real
default model (`qwen2.5:7b-instruct`) and hand-scored:

| threshold | matched | notes |
| --- | --- | --- |
| 0.30 | 40/49 | identical set to 0.40 |
| **0.40** | **40/49** | **39 of 40 correct — 97.5% precision, 82% coverage** |
| 0.50 | 37/49 | removes the one wrong match (0.49), costs two correct |
| 0.60 | 31/49 | |

The threshold is **not load-bearing between 0.30 and 0.40**. The 0.40/0.50
choice is within noise at this sample size, on one book, with one of the two
chapters unusually quotation-heavy dialogue (which flatters the scores).
Revisiting it against a wider fact library is a scoring job, not a code
change.

## Spoiler safety
A new render surface, and `tests/test_spoiler_safety.py` says a surface its
gate is not pointed at has no gate. Two structural rules:
- A citation reads **only the chapter the fact belongs to**. Callers cite
  only facts that passed `facts_as_of`, so that chapter is one the reader has
  read.
- **Nothing is derived from the whole book** — no "chapter 12 of 75", no
  percentage through the *book*, no page count. Those are exactly the leak
  the truncated-library equivalence test exists to catch. The percentage this
  module does render is a position within one chapter, computed from that
  chapter's text alone.

Both are sabotage-verified: quoting chapter N+1 fails the sentinel *and*
equivalence tests; adding a whole-book-derived chapter count fails
equivalence **only**, which is the case a content-matching test structurally
cannot see.

## Dependencies
- Internal: `bookrag.storage.library_root`. Reads `metadata.json` and
  `chapters.jsonl` directly rather than through `storage.load_chapters`,
  which would load every chapter.
- External: none.

## Data Contracts
- In: a `book_id`, a `chapter_index`, and a fact's `statement`. `cite_facts`
  takes anything with `book_id`, `chapter_index` and `statement` — in
  practice `query.Fact`.
- Reads `metadata.json` (`title`, `omnibus`) and one `chapters.jsonl` record
  (`title`, `text`, `pages`).
- Out: `Citation`, or `None` when the book or chapter cannot be read at all.

## Open Questions / TODOs
- The threshold is calibrated on one book and 49 statements. A reader's
  extracted library would settle the 0.40-vs-0.50 question properly.
- No within-chapter locator exists for a book that is both unpaged and whose
  passage does not match — those citations stop at the chapter.
- `position` is a character offset ratio, so a chapter with a long front
  matter block reports a position skewed against the prose. Fine for "roughly
  where", which is all it claims.
