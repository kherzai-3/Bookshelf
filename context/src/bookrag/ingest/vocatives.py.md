---
source: src/bookrag/ingest/vocatives.py
last_synced: 2026-09-15T15:51:06Z
source_hash: 6cb49f90c81d189ac46d18c83c9583d3f5a1d730
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
  `ambiguous: list[tuple[str, int, int]]`, `first_person_chapters: list[int]`,
  `chapters_considered: int`, `quote_style: str | None`, plus an
  `is_first_person` property.
- `detect_narrator_aliases(chapters: list[Chapter]) -> NarratorAliases`

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
- **Measured accuracy is 6 of 7 on one book, and needs re-verification across
  more.** The one wrong result is instructive: the two-hander assumption breaks
  in a three-party scene, where a guard faces the narrator and says "I suppose
  she will have to see him, Captain" - speaking *about* the narrator *to* a
  third person - and "captain" is harvested. `cousin` and `thief` looked wrong
  and turned out genuine on inspection.
- **The Magic Thief counts above predate the trailing-comma fix** and will be
  higher once re-measured; the book was deleted from this machine before the
  fix landed (`bookrag remove` destroys `source.epub`, which `ingest` had
  already moved out of `data/incoming/` - see that separate hazard).
- **Nothing consumes the result yet.** The intended next step is seeding
  `extract.resolve` with a confirmed alias set before extraction, so the
  fragmentation never forms, rather than repairing it afterwards with
  `doctor --merge-name-variants`. That needs a confirmation surface first -
  this reports candidates and applies nothing.
- Third-person attribution is unsolved and deliberately out of scope. It needs
  an addressee, which is a different problem from finding a vocative.
