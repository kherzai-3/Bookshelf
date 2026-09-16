---
source: src/bookrag/ingest/vocatives.py
last_synced: 2026-09-16T19:53:59Z
source_hash: 6ab52b8eab9d18e52cd0f76c0a1de878c322d0ed
---

## Purpose
Reads every name the other characters use for a first-person narrator, out of
chapter text alone - no model, no extraction, no entity registry. The catalog
otherwise files one character under every name the book uses for them ("Conn",
"Connwaer", "boy", "lad", "gutterboy") as separate people.

**Why it runs here and not in `doctor`.** The repair for this previously lived
in `bookrag doctor --merge-name-variants`, and `run_doctor` has exactly one
call site: the `doctor` subcommand. Nothing automatic reaches it. The user who
reported the problem ran clone → `install.py` → `ingest` → `extract` and would
never have typed it. Running at ingest puts the answer on the path people
actually walk, and early enough that extraction could eventually be told about
it rather than having its output patched afterwards.

## Public Interface
- `NarratorAliases` (dataclass) — `aliases: list[tuple[str, int]]`,
  `addressed_by_narrator: list[tuple[str, int]]`,
  `ambiguous: list[tuple[str, int, int]]`,
  `speakers: list[tuple[str, int, int]]`, `first_person_chapters: list[int]`,
  `chapters_considered: int`, `quote_style: str | None`, plus an
  `is_first_person` property.
- `detect_narrator_aliases(chapters: list[Chapter]) -> NarratorAliases`
- Consumed by `cli.narrator_alias_lines` (the ingest section) and
  `bookrag aliases <book_id>`. **Nothing here is ever applied** - linking is
  `library.link_names`, driven by a person choosing from this list.

## The precision correction (read this before trusting any number)
An earlier revision of this doc reported **6 of 7 correct**. That was
small-sample luck and is now known to be wrong. Re-ingesting the reported book
after a trailing-comma fix roughly **tripled recall** (connwaer 3→24, boy
34→106), the candidate list went from 7 to 16, and three real characters
appeared in it: `argent`, `trammel`, `captain`.

The cause is structural, not a tuning problem. In a first-person novel the
narrator constantly **overhears** conversations he is not part of, so "spoken
by someone other than the narrator" does not mean "addressed to the narrator".
`"Well, Trammel?" Brumbee asked` is attributed correctly to Brumbee, who
correctly is not the narrator, and is still addressing Trammel.

The fix is `_times_speaking` plus `_MIN_ADDRESSED_TO_SPOKEN`: the narrator of a
first-person book is never a speech-tag subject, so a candidate caught speaking
belongs to somebody else. Measured on the reported book it separates cleanly -
every confirmed error at or below a 1.0 ratio (trammel 0.12, argent 0.16, you
0.29, captain 0.75), every confirmed alias above it (connwaer 24.0, boy 5.6,
conn 4.3). One correct name is lost at the boundary (gutterboy, exactly 1.0),
and that trade is deliberate: a missed epithet costs a retrieval near-miss, a
kept character costs a merged identity.

Counted over **first-person chapters only**. A third-person section names its
characters in speech tags, and including the reported book's later
third-person sections made "conn" and "connwaer" themselves look like speakers.

Surviving list on that book: `boy, conn, connwaer, lad, sir, dear, magister,
thief, shadow, blackbird, cousin`. Six are confirmed correct; `sir`/`dear` are
generic terms of address and would be poor links. **Still a candidate list, not
an answer.**

## Key Decisions
- **The signal is who is speaking, not what is said.** A vocative sits in
  quoted dialogue; in a first-person book an utterance spoken by anyone other
  than the narrator is, in a two-hander, addressed *to* them. Splitting
  vocatives by speaker separates "what people call me" from "what I call
  people" and needs nothing else. Measured on the reported book that split is
  total: `others → boy 34, conn 12, lad 4, connwaer 3` against
  `narrator → nevery 12, pip 7, kerrn 6`, with no overlap.
- **Two earlier approaches were tried on real data and rejected**, and both
  failures are worth not repeating:
  - *A naming construction in the text* ("Connwaer, called Conn"). The book
    never says it. Zero sentences in 230,518 words contain both names; the link
    is made exactly once, as bare apposition in dialogue (`"Conn," I answered.
    "Connwaer."`). The construction is also loose, not merely absent - it fires
    59 times in Ranger's Apprentice and 128 in Moby Dick, nearly always about a
    class ("beasts known as the Kalkara").
  - *A first-person pronoun in the surrounding narration.* In a first-person
    book every narration window says "me", so this ranked the narrator's word
    for his master (`nevery`, 39) alongside his own name.
- **Narration mode is judged per chapter, not per book** - a safeguard, not a
  refinement. The reported book is a five-novel omnibus whose later sections
  switch to a third-person POV, and there "the boy" is a servant rather than
  the protagonist. Per-book judgement would attach a stranger's epithet to the
  protagonist, which is exactly the "an epithet is chapter-scoped in a way a
  name isn't" hazard the README warned about. Measured, those two chapters
  score 0.05 and 0.13 against a threshold of 4.0 and are dropped.
- **`_FIRST_PERSON_PER_100_WORDS = 4.0`, measured not guessed.** Per chapter,
  dialogue stripped: The Magic Thief runs a median of 7.11 and a lower quartile
  of 6.03; Ranger's Apprentice peaks at 3.45 with a median of 0.48. 4.0 sits in
  the gap. Dialogue *must* be stripped first - everyone says "I" inside
  quotation marks, so leaving it in makes every novel look first-person.
- **Quote pairs are detected, not assumed.** Publishers differ: The Magic Thief
  uses curly doubles, Ranger's Apprentice curly singles. A hardcoded pair fails
  *silently* - zero spans, which reads exactly like "this book has no dialogue"
  and was nearly recorded as a finding about third-person novels. The closing
  curly single is also the apostrophe in "don't", so it carries a
  `(?![A-Za-z])` guard.
- **The trailing vocative terminator includes a comma.** In `"Come along, boy,"
  he said` the comma belongs to the sentence but sits inside the quotation
  marks. Allowing only `.?!` silently drops every vocative in an utterance that
  continues into its attribution, which is most of them. Caught by
  `test_curly_single_quotes_are_found_too`, not by inspection.
- **Speech verbs are a closed list.** Generalising to "any word ending -ed or
  -s" was tried and immediately degraded attribution: it matched ordinary verbs
  in the following sentence and filed the narrator's own lines under someone
  else.
- **The alias filter is comparative, not absolute.** A misread attribution tag
  drops a stray count in the wrong column, so a name is kept only if the
  narrator is addressed by it more often than they use it for others. Real
  case: `nevery` landed 2 against 12 and is reported under `ambiguous`.
- **`_MIN_TIMES_ADDRESSED = 2`.** The trailing-vocative shape also matches an
  utterance merely ending in ", <word>." - real one-offs harvested from the
  reported book include "hurry", "quiet" and "stoichiometry". Every genuine
  alias in that book cleared 2.
- **Third-person books return nothing on purpose.** Vocatives are still
  extractable there (Ranger's Apprentice yields `will`, `halt`, `horace`,
  `gilan`, `boy`), but nothing in the text says *who* a given "boy" was aimed
  at, and inventing an answer is how a wrong identity gets recorded.

## Data Contracts
In: `list[Chapter]` (see `ingest/chapter.py`) - `index` and `text` only.
Out: `NarratorAliases`, lowercased names with counts. Nothing is written; this
is a report. `cli.narrator_alias_lines` renders it under ingest's "Names for
the narrator" section.

## Open Questions / TODOs
- **Accuracy is established on exactly one book.** See "The precision
  correction" above for why the first estimate was wrong; the same thing could
  happen again on a book with a different dialogue style. Every number here is
  n=1 until a reader runs it on something nobody here has seen.
- **`sir`, `dear`, `magister`, `shadow`, `blackbird` are unresolved** on the
  reported book - generic terms of address, or possibly real epithets. They
  survive the filters and a person has to judge them.
- **Consumed by `library.link_names` only when a person chooses.** Linking
  before extraction is what stops the split forming, and is now proved end to
  end; see that function and `test_link_names_before_extraction_stops_the_split_
  forming`. Nothing links automatically, and it should stay that way while the
  candidate list still contains `sir`.
- **A generic epithet must not become a retrieval alias, and this is measured,
  not feared.** `query.select_relevant_facts` matches a question against an
  entity's aliases by case-insensitive *substring*, so an alias of "boy" makes
  every question containing the word "boy" retrieve that character's entire
  fact set. Simulated on the real library by giving Will the aliases
  `["boy", "lad"]`:

  | question | retrieved | verdict |
  |---|---|---|
  | "Who is the boy?" | 284 facts, Will | right, and the whole point |
  | "What did Halt teach the boy?" | 445 facts, Halt + Will | right |
  | "Describe the Skandian boy" | 294 facts, Skandians + **Will** | **wrong** |

  The last row is the failure: "the Skandian boy" is a different boy, and the
  epithet dragged in the protagonist. The same hazard is worse in the reported
  book, where "boy" means the protagonist for four novels and a servant in the
  fifth. So the two kinds of result this module finds are **not
  interchangeable**: a name-like alias ("Conn", "Connwaer") is safe to merge
  and to match on, while a generic epithet ("boy", "lad", "cousin") is good
  evidence about who is being addressed and a bad retrieval key. Whatever
  consumes this has to separate them - the obvious split is whether the
  vocative is a proper noun, which is cheap and already implied by the data.
- Third-person attribution is unsolved and deliberately out of scope. It needs
  an addressee, which is a different problem from finding a vocative.

## `AliasCandidate` and `auto_link_plan`
- `AliasCandidate(name, times_addressed, times_capitalised)` with
  `reads_as_a_name` (≥80% capitalised) and `is_anyones_term_of_address`.
  `name` keeps the **surface form the book used**, so a linked alias reads like
  the book rather than a lowercased token.
- **Capitalisation is counted only in trailing vocative position**
  (`_vocative_in_trailing_position`). A leading vocative is sentence-initial and
  capitalised whether it is "Conn" or "Boy", so counting those would make every
  epithet look like a name. Measured, the split is near-total: Connwaer 24/24
  and Conn 22/22 against boy 1/106, lad 0/14, sir 0/12, thief 0/3.
- `auto_link_plan(found) -> (names, epithets)` — what is safe to link with
  nobody asked. **Names need two independent signals.** Capitalisation alone
  admits `Magister` (5/5 capitalised), which is Keeston addressing *Nevery*
  while the narrator stands by; a string relationship alone is the 0-for-6
  prefix rule. Requiring both keeps Conn/Connwaer and rejects Magister.
  Epithets ride along on whatever the names produced, minus
  `_ANYONES_TERM_OF_ADDRESS` (`sir`, `dear`, ...). **Never links an epithet
  alone** - without a name to attach it to there is no evidence whose epithet
  it is, and a lone "boy" would become a character called boy.
- Verified on all five real books: Magic Thief links Conn+Connwaer as names and
  boy/lad/thief/cousin as epithets; the other four link nothing.

## Correction: epithets were nearly discarded on fabricated evidence
An earlier revision excluded epithets from linking, citing a query -
"describe the Skandian boy" - that appears **zero times** in the book it was
run against. It was invented. Epithets are not a side case: on the reported
book they outweigh the names (boy 495 references, thief 136, gutterboy 100,
against Conn 344 and Connwaer 162). The real constraint is *where* they are
safe, not whether to keep them - see the two-list rule in
`extract/resolve.py`'s context doc.
