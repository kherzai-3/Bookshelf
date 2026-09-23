---
source: src/bookrag/locate.py
last_synced: 2026-09-23T13:41:38Z
source_hash: f68793e20d92a7cf508d17536d2b9dcfd2315dd5
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
- `volume_at(volumes, chapter_index) -> tuple[str, int] | None` — which
  stitched-in book a chapter belongs to, and its 1-based number within it.
- `_MIN_PASSAGE_SCORE`, `_UNSEEN_IDF`, `_PAIR_PENALTY`, `_MAX_QUOTE_CHARS`.

## Key Decisions
- **The deliverable is a rendered location, not a storage layout.** What the
  database keys a chapter as is irrelevant; what matters is that the reader
  is told something they can act on. This is the correction that re-scoped
  the whole item — rank 04's omnibus split was ranked as a *precondition* for
  citations on the theory that per-book storage was required, and it was not.
  A display-label map over the same volume spans produces the same string.
  **That is now what the code does**: the split was removed and
  `ingest.volumes` records spans, which `volume_at` reads back here.
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
  reads as the tool being wrong about the *book*. 51 of 181 real statements
  get no quote and only a structural location; that is the designed
  degradation, not a failure — and in one sampled chapter it is *all* 14 of
  them (see Measurement).
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
181 statements from **eleven chapters of six books**, produced by the real
default model (`qwen2.5:7b-instruct`) and hand-scored one at a time against
the whole matched sentence (the shipped 220-character quote cap hides the
half of a long sentence that carries the match, and judging on the rendered
quote alone reverses two verdicts):

| threshold | quoted | coverage | correct | precision |
| --- | --- | --- | --- | --- |
| 0.30 | 153 | 85% | 135 | 88% |
| 0.32 | 150 | 83% | 134 | 89% |
| **0.40** | **130** | **72%** | **118** | **91%** |
| 0.50 | 115 | 64% | 106 | 92% |
| 0.60 | 100 | 55% | 93 | 93% |
| 0.70 | 80 | 44% | 75 | 94% |

**The threshold is worth very little in either direction** — six points of
precision across a range that costs 41 points of coverage. Raising it is a
bad trade outright. Lowering it to 0.32 is a real trade rather than a free
one (20 more quotes at 80% marginal precision) and is declined because a
wrong quote costs more than a missing one; below ~0.30 marginal precision
falls to 45%. **0.40 stays, and the useful result is that it barely
matters.**

### What the earlier one-book measurement got wrong
The 49-statement Ranger's Apprentice sample reported **97.5% precision at
82% coverage** and concluded the threshold was inert between 0.30 and 0.40.
Both conclusions were artefacts of one book:
- precision on six books is **91%**, and the same book scores **81%** on two
  different chapters;
- 0.32 matches 20 more statements than 0.40, so the value is not inert.

The sweep that produced the "inert" reading only moved the threshold
*upward*, so it could not see the correct quotes sitting just below 0.40.

### Precision is capped by errors no threshold can reach
The three highest-scoring wrong matches score **1.00, 0.98 and 0.98**, and in
all three the *statement* is false while the matcher correctly found the
sentence the model misread ("Will was a Battleschool apprentice" — the
sentence says Horace). The rest are near misses at 0.48–0.81, where a rare
word dominates: four statements of the form "Gilan inspected the garrison
house" all matched "He inspected the tip of his finger", because weighted
recall deliberately does not penalise a short sentence.

### Coverage is set per chapter, not by the threshold
What decides whether a chapter gets quotes is the share of the model's words
that appear **nowhere in the chapter**, which `_UNSEEN_IDF` charges at full
weight in the denominator. Across the eleven chapters that share tracks the
median score at **r = −0.81**: at 5–10% unseen the median is 0.57–0.86; in
the one chapter at 33% — an Eye of the World chapter whose statements are
all interior-state summaries — the median is 0.25 and **not one of its 14
statements clears 0.40**. Per-book coverage at 0.40 ranges 0%–100%. A single
global threshold cannot serve both kinds of chapter; that, not the constant,
is what to fix if coverage ever matters more.

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
- Reads `metadata.json` (`title`, `volumes`) and one `chapters.jsonl` record
  (`title`, `text`, `pages`).
- Out: `Citation`, or `None` when the book or chapter cannot be read at all.

## Open Questions / TODOs
- The 0.40-vs-0.50 question is **closed by rejecting it** — see Measurement.
  What replaced it: coverage is a per-chapter property driven by how much of
  its own vocabulary the model uses, and a global threshold cannot adapt to
  it. Scaling `_UNSEEN_IDF` by how paraphrased a statement is, or scoring
  against a chapter-normalised baseline, is the open direction.
- No within-chapter locator exists for a book that is both unpaged and whose
  passage does not match — those citations stop at the chapter.
- `position` is a character offset ratio, so a chapter with a long front
  matter block reports a position skewed against the prose. Fine for "roughly
  where", which is all it claims.
