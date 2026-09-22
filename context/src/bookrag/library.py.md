---
source: src/bookrag/library.py
last_synced: 2026-09-22T20:19:13Z
source_hash: 437e7a316f2c7fdbf6cd5c51cfb2ffa175d09e56
---

## Purpose
Library-wide inspection and maintenance, sitting above `storage.py` (one
book's persistence) and `extract/resolve.py` (the global entity registry):
list/show what's in the library and how far extraction has gotten, remove a
book cleanly, and a read-only-by-default consistency check ("doctor") for
drift accumulated by hand-editing library files directly - exactly the kind
of cleanup done manually several times earlier this project (a stale
`index.json` entry after a directory was deleted outside the CLI, orphaned
`entities.json` entries with zero facts actually backing them). `cli.py`'s
`list`/`show`/`remove`/`doctor` subcommands are thin wrappers around this
module's functions.

## Public Interface
- `BookSummary` (dataclass) — `book_id, title, author, series, orphaned,
  content_type, chapter_count, fact_count, chapters_extracted, entity_count,
  volumes`, plus a `partial` property (see Key Decisions). `volumes` is
  `metadata.json`'s list of `{title, label, start, end}` spans (see
  `ingest/volumes.py`) and is `None` for almost every book; it is carried
  here only so `cli._show` can list the separately published books stitched
  into one file, which is the one place a reader can check the detector's
  reading of it after ingest has scrolled away.
- `list_books(root=None) -> list[BookSummary]` — one summary per
  `index.json` entry.
- `show_book(book_id, root=None) -> BookSummary` — raises `ValueError` if
  `book_id` isn't in `index.json` at all.
- `RemoveResult` (dataclass) — `removed_directory, removed_index_entry,
  entities_pruned, entities_deleted`.
- `remove_book(book_id, root=None) -> RemoveResult` — deletes
  `data/library/<book_id>/`, its `index.json` entry, and prunes `book_id`
  from every entity's `book_ids` in `entities.json` (deleting any entity
  this leaves with none). Raises `ValueError` only if `book_id` is unknown
  to *both* the index and the filesystem - otherwise cleans up whichever
  parts of it actually exist (handles the orphaned-index-entry case too).
- `DuplicateEntity` (dataclass) — `entity_id, canonical_name, type,
  book_ids, fact_count` - one member of a possible-duplicate cluster.
- `detect_duplicate_entities(root=None) -> list[list[DuplicateEntity]]` —
  groups entities by `extract.resolve.match_key(canonical_name)`,
  **regardless of `entity_type`** (unlike `resolve_entity`'s own matching -
  see Key Decisions), returns only groups with more than one entity.
- `MergeResult` (dataclass) — `kept_entity_id, merged_entity_ids: list[str],
  facts_rewritten: int`.
- `merge_entities(entity_ids, keep=None, root=None) -> MergeResult` —
  merges 2+ existing entities into one (see Key Decisions for exactly
  what it rewrites). Raises `ValueError` if fewer than two of
  `entity_ids` actually exist, or if `keep` isn't one of them.
- `NameVariant` (dataclass) — `entity_id, canonical_name, type, book_ids,
  fact_count` - deliberately the same four display fields as
  `DuplicateEntity`, so `cli.py`'s `_confirm_and_merge` handles both.
- `NameVariantCluster` (dataclass) — `members: list[NameVariant], reasons:
  list[str], book_id: str`.
- `detect_name_variants(root=None) -> list[NameVariantCluster]` — one person
  under several names (see "Name-variant detection" below).
- `LinkResult` (dataclass) — `entity_id, canonical_name, aliases: list[str],
  created: bool, merged_entity_ids: list[str], facts_rewritten: int`.
- `link_names(book_id, names: list[str], root=None) -> LinkResult` — declares
  several names to be one character. See "Linking names" below.
- `DoctorReport` (dataclass) — `orphaned_index_entries: list[str],
  stale_entity_book_refs: list[tuple[entity_id, book_id]],
  orphaned_entities: list[str], duplicate_entity_groups:
  list[list[DuplicateEntity]], fixed: bool`.
- `run_doctor(root=None, fix=False) -> DoctorReport` — read-only by default;
  `fix=True` also applies the cleanup (see Key Decisions for exactly what -
  `duplicate_entity_groups` is never included in what `fix` touches).

## Key Decisions
- **`detect_duplicate_entities` deliberately ignores `entity_type` when
  grouping**, unlike `resolve_entity`'s own type-scoped matching. Real
  motivating case: one creature ("Wargal(s)") had fragmented into 5
  catalog entities across *both* name spelling and `entity_type`
  (`character`/`setting`/`theme`) - a type-scoped detector would only ever
  find same-type duplicates and miss most of that real cluster. A real
  full-library `bookrag doctor` run found 12 such clusters, several
  type-crossing (a publisher name typed as both `setting` and
  `character`; "Skandians" split three ways) and at least one that was
  pure name-variant with **no** type drift at all ("Implementation
  Intention"/"Implementation Intentions", both already `concept`) -
  confirming `match_key` normalization has real value independent of the
  type-drift fix in `extract/pipeline.py`.
- **Detection only - `bookrag doctor --fix` never auto-merges duplicate
  clusters**, unlike its other three checks (which are all safe,
  reversible-in-spirit cleanups of clearly-dead data). Merging picks a
  winner and permanently rewrites fact ownership - a real, consequential
  judgment call that needs a human to confirm, not a blind default action.
  `merge_entities` is exposed separately (`bookrag doctor
  --merge-duplicates`, confirmed per cluster unless `--yes`).
- **`merge_entities` picks the most-facts entity as `keep` by default** -
  matches the real, lopsided pattern already observed (one real cluster's
  dominant entity held 73% of the group's facts). Every merged-away
  entity's `canonical_name` and its own `aliases` become aliases of the
  kept entity - gated only on an exact (case-insensitive) match to the
  kept entity's own name, **not** on `match_key` equality, since two
  surface forms sharing a `match_key` (e.g. "Wargals"/"The Wargals") are
  still two real, distinct strings worth recording once merged - this is
  what finally populates `aliases`, a field nothing else in the codebase
  ever writes to (see `extract/resolve.py`'s context doc). Facts are
  rewritten in every book directory any merged entity referenced, not just
  one - a real entity can span multiple books via `book_ids`.
- **"How far extraction reached" is `max(chapter_index) + 1` from
  `facts.jsonl`, not a count of chapters that have at least one fact.**
  These genuinely differ on real data: a fully successful `extract_book` run
  still writes zero fact records for a chapter `extract.pipeline` decided
  was too short to plausibly be narrative (front matter, a one-line
  interstitial) - confirmed directly against Ranger's Apprentice, which has
  facts for 72 of its 75 chapters but the highest `chapter_index` present is
  74 (the run reached the end; the 3 zero-fact chapters are legitimately
  non-narrative). Counting only chapters-with-facts would have wrongly
  reported a fully-extracted book as partial. This heuristic has its own
  blind spot, not yet hit in practice: if the very *last* chapter is itself
  one of the zero-fact ones, a complete run would still read as one chapter
  short. There's no persisted "chapters actually attempted" record to do
  better than this without adding one - see Open Questions.
- **`BookSummary.partial`** is `True` only when `chapters_extracted` is
  known and less than `chapter_count` - `None` (never extracted) is
  deliberately not "partial", it's a separate state (`fact_count is None`).
- **`remove_book`/`run_doctor --fix` both delete an entity outright once its
  `book_ids` becomes empty** - nothing else could ever reference it again
  once its only book(s) are gone. This reuses
  `resolve.prune_book_from_entities`, the mutation-in-place counterpart to
  `resolve_entity`'s "add a book_id" - kept in `resolve.py`, not duplicated
  here, since that's where `entities.json`'s shape is already understood.
- **`run_doctor`'s three checks are independent, not a single "is this
  entity valid" pass**: `orphaned_index_entries` (index says a book exists,
  filesystem disagrees), `stale_entity_book_refs` (an entity still lists a
  `book_id` that's gone - reported even for an otherwise-healthy entity with
  other valid book_ids, since the stale ref itself is real leftover data),
  and `orphaned_entities` (zero facts reference this entity in any book that
  *does* still exist - the stronger, "genuinely useless" check, requiring an
  actual `facts.jsonl` scan per book, not just a `book_ids` list check).
  `--fix` prunes stale refs and deletes orphaned entities as two separate
  actions on the same entity where applicable.
- **`remove_book` is deliberately tolerant of partial/orphaned state**
  (works if only the directory exists, only the index entry exists, or
  both) rather than requiring a fully-consistent book first - this is what
  lets `bookrag doctor --fix`'s orphaned-index-entry cleanup and a normal
  `bookrag remove` share the same underlying logic instead of needing two
  separate code paths.

## Dependencies
- Internal: `bookrag.storage` (`library_root`, `load_index`, `load_metadata`,
  `remove_from_index`), `bookrag.extract.resolve` (`load_entities`,
  `save_entities`, `prune_book_from_entities`)

## Data Contracts
- Reads `facts.jsonl` records only for their `chapter_index`/`entity_id`
  fields (see `extract/pipeline.py`'s context doc for the full record
  shape) - never touches `category`/`statement`.

## Open Questions / TODOs
- The `max(chapter_index) + 1` completion heuristic (see Key Decisions) is
  an approximation, not a real "chapters attempted" record - it would be
  made exact by `extract_book` persisting its own progress, which is
  exactly what the planned resumable-extraction feature needs anyway (see
  `extract/pipeline.py`'s context doc). Worth unifying when that's built,
  rather than solving the same problem twice.
- `resolve_entity` (see `extract/resolve.py`'s context doc) matches
  globally across the whole library, not scoped to a series - `doctor`'s
  `orphaned_entities` check doesn't attempt to detect a *coincidental*
  cross-book name collision (two unrelated books' same-named, same-typed
  entities silently sharing one `entity_id`); it only checks whether an
  entity has zero facts anywhere, which a collided entity would still pass.
  No real collision has been observed in the current library.

## `unnamed_fact_refs` - facts pointing at an unregistered entity
The inverse of `orphaned_entities`, and the damaging direction of the same
inconsistency. An orphaned entity is a harmless empty registry row; a fact
referencing an entity the registry has no record of is **real content that
renders as a raw id and cannot be found by name**.

`--fix` deliberately leaves these alone, unlike the three checks it does
repair. The name is unrecoverable (a fact stores only the `entity_id`), so the
only honest repairs are re-extracting the affected chapters or accepting the
loss - both the user's call, not a cleanup pass's. Deleting the facts would be
destroying real content to satisfy a consistency check.

Found on the project's own library: 14 ids covering 38 facts, all from
chapters 4-10, caused by `extract/pipeline.py` saving the registry only in a
`finally` that an abrupt kill never reached (fixed there; see that context
doc).

## Cross-book entity split (`detect_cross_book_entities` / `split_cross_book_entity`)

The counterpart to `extract/resolve.py`'s identity scoping: that stops new
wrong merges, this undoes existing ones. Scoping alone cannot, because a
re-extraction resolves against the same registry - all four merges in the
real library survived a full 5h27m re-run untouched.

- `detect_cross_book_entities(root=None) -> list[CrossBookEntity]` — entities
  claimed by 2+ books that do **not** share one series name. Sharing across a
  series is the intended feature and is never reported. Carries
  `facts_per_book` so the report shows where the content actually sits.
- `split_cross_book_entity(entity_id, root=None) -> SplitResult` — gives each
  book its own record and rewrites that book's fact `entity_id`s.
- Surfaced by `bookrag doctor`, applied by `--split-cross-book`. Deliberately
  **not** part of `--fix`, same posture as `--merge-duplicates`: rewriting
  fact records across book files is higher-stakes than deleting an orphan.

**Why this is safe to automate when the dangling-reference repair is not.**
`unnamed_fact_refs` stays unrepairable because a fact stores only an
`entity_id` and the name is genuinely gone. Here nothing is lost: facts are
already partitioned by book file, so which book a fact belongs to is read,
not guessed, and both halves keep the same `canonical_name` and `type` -
they merged precisely because they spell alike.

**Key decisions**
- The book with the **most facts keeps the original id**, so the common case
  rewrites the fewest records - and it matches `merge_entities`'s own
  keep-the-dominant-entity convention.
- A book_id with **zero** facts is dropped rather than given an entity.
  It is a stale reference, not a second character: `extract --restart`
  truncates `facts.jsonl` but leaves `entities.json` alone, so a book_id
  recorded by a pre-restart run outlives every fact that justified it.
  Observed live - "Michael" claimed Ranger's Apprentice with 0 facts there.
- **Aliases are not copied** to the new entity. An alias could have come from
  either book and this cannot know which; losing one costs a retrieval
  near-miss, inventing one asserts a name a book may never have used.

**Verified on real data** before touching the real library: run against an
exact copy of the four-book library, then the copy re-checked - 2,035 facts
before and after, zero dangling references, zero cross-book entities
remaining. Applied to the real library with the same result.

## Linking names (`link_names`)

The answer to "would a re-extraction fix a fragmented character?" - **no, and
that was tested rather than argued.** The same three-chapter book extracts as
two entities unseeded (`Conn` in chapters 0 and 2, `Connwaer` in chapter 1) and
one seeded. A fresh ingest plus re-extraction reproduces the split exactly;
what decides it is whether `entities.json` already knows the alias when
extraction starts.

Nothing new was needed to make that work: `extract.resolve.resolve_entity` has
always matched an incoming entity name against a known entity's `aliases`
(scoped by `book_ids`), so writing the alias set *first* makes every later
mention resolve to one entity and the fragmentation never forms. Confirmed on
the real 84-chapter Magic Thief omnibus - after linking `Conn,Connwaer`, a full
extraction leaves **no separate "Connwaer" entity at all**.

**Works in both directions, on purpose.** Run after extraction it merges
whatever entities already hold those names, reusing `merge_entities` rather
than reimplementing it. A real extraction costs hours, so a user who only
works out who is who *afterwards* must not be told to start over.

**Takes explicit names, never a detector's output.** `ingest.vocatives` reports
candidates, and its own accuracy notes record that a generic term of address
(`sir`, `dear`) can survive its filters. A name-like alias is safe to link; a
generic epithet is a bad retrieval key, because `query.select_relevant_facts`
matches aliases by substring and an alias of "boy" makes every question
containing that word retrieve this character (measured - see
`context/src/bookrag/ingest/vocatives.py.md`). Choosing is a person's job, and
`cli.py`'s `aliases` command says so in its output.

## Name-variant detection (`detect_name_variants`)

The third sibling of `detect_duplicate_entities` and
`detect_cross_book_entities`, and the answer to "what populates `aliases`
from a book?". Nothing did: 2 of 493 entities in the real library had one,
and both came from a hand-run `doctor --merge-duplicates`. **The storage and
retrieval halves were already built** - `resolve_entity` matches aliases,
`query.select_relevant_facts` searches them - and `merge_entities` already
folds a merged-away name into the survivor's alias list. So this adds
detection only; applying a cluster goes through the existing merge.

`detect_duplicate_entities` structurally cannot find these: it groups by
`match_key`, and "Baron Arald" / "Arald" do not share one.

**Four rules, each scoped to one book, three of them also to one entity type.
All four were chosen by measuring candidate precision on real data rather
than by reasoning about what ought to work** - the survey lives at
`_title_variant_pairs` / `_fuller_name_pairs` / `_prefix_shaped_pairs` /
`_residue_variant_pairs`:

1. **`_title_variant_pairs` — a rank in front of a name.** "Baron Arald" ≡
   "Arald". 10 candidates on real data, **10/10 correct**. Needs almost no
   guarding because it compares the remainder *after* stripping the title, so
   two people sharing a rank ("King Duncan", "King Swyddned") never collide.
   **Characters only**, for the same reason containment is: an honorific in
   front of a *person's* name leaves the person unchanged, but in front of a
   concept it is part of the term. Found latent in the real library while
   checking nonfiction safety - "Master Player" in *Finite and Infinite Games*
   strips to "Player", and a master player is emphatically not a player. It had
   never fired only because no bare "Player" entity exists yet; a re-extraction
   could create one at any time. Restricting to characters costs nothing
   measured: all 10 real hits were characters, and the real library still
   yields the same 16 clusters after the restriction.
   `_TITLES` is a closed list plus `_MASTER_RANK`, a shape rule for the
   productive `-master` compound (Battlemaster, Craftmaster, Harbourmaster) so
   that part isn't overfitted to one book's vocabulary.
2. **`_fuller_name_pairs` — a given name and a fuller form.** "Alyss" ≡
   "Alyss Mainwaring". Raw containment across all types gave **44 candidates,
   ~8 right**; four guards separate them: characters only, no conjunction in
   the longer name, the shorter name must not reduce to a bare rank, and the
   shorter name must sit inside **exactly one** longer name.
3. **`_stated_variant_pairs` — the book says so.** "Connwaer, called Conn".
4. **`_residue_variant_pairs` — a decorated form of a better-attested name.**
   "Elder Fang Yuan" ≡ "Fang Yuan". See "The residue rule" below.

**The prefix shape is not evidence.** `_prefix_shaped_pairs` alone proposed 6
pairs on the real library and **every one was wrong** (`Machine`/`Machinery`,
`King`/`Kingdom`, `Skandia`/`Skandians` - a place and its people). It is only
a shortlist; `_states_they_are_one` then requires the text to link the two
names with a naming connector ("called", "known as", "short for"). This is
what makes rule 3 safe, and it is why the reported Conn/Connwaer case needs
the book to state the link rather than being inferred from the spelling.

**Guards, and why each is a veto rather than a tie-break:**
- **Ambiguity vetoes.** A short name inside two longer ones is the shape of
  two people sharing a given name. Saying nothing costs a retrieval near-miss;
  guessing costs an invisible, unmergeable wrong identity - the same asymmetry
  that made `resolve_entity`'s scope deliberately narrow.
- **Conjunctions.** "Tug and Blaze" is two horses the extractor filed as one
  entity. Both halves are contained in it, so without the guard each merges
  *into the compound*, which is the wrong survivor.
- **Characters only.** In a book about the difference between a finite game
  and an infinite one, "Finite Game" contains "Game" and is not a longer name
  for it.

`_connected_clusters` is union-find over the proposed pairs, so
"Battlemaster David" / "Sir David" / "David" arrives as **one** decision.
Three overlapping pair-prompts would be worse than useless: answering the
first changes what the other two mean.

**Measured on the real library: 16 clusters, 34 entities, 0.16s, 16/16
correct.** The one that looked wrong on inspection wasn't - Moby Dick's
"Coffin" (12 facts) is Peter Coffin the innkeeper, not Queequeg's coffin;
all 12 are the same statement repeated, which is the separate duplicate-spike
bug showing through.

**Reported but never applied by `--fix`**, same posture as duplicate clusters
and cross-book splits: merging picks a winner and permanently rewrites fact
ownership. `bookrag doctor --merge-name-variants` applies it, per cluster,
with the reason shown before the question.

**Retrieval effect, measured end to end** on a copy of the real library
(before → after applying all 16 clusters), which is the only thing that makes
this feature worth anything:

| question | before | after |
|---|---|---|
| "Tell me about Arald" | 10 facts | **49 facts** |
| "Tell me about David" | 1 fact | **11 facts** |
| "Who is Baron Tyler?" | 6 facts, Tyler only | 6 facts, Tyler only |
| "What is Baron Fergus like?" | 5 facts, Fergus only | 6 facts, Fergus only |

The two control questions are the point: merging Arald does **not** drag the
other barons in. Entity matching is per-entity and the merged aliases are full
names, so "Baron Tyler" never matches Arald's record. (A separate entity
literally named "The Baron" does match any question containing "baron" - that
is `select_relevant_facts`'s substring tier being generous, and predates all
of this.)

**Open question deliberately left:** epithets ("the boy", "bird" for Conn)
are out of reach of all three rules, since they share no string relationship
with the real name and are chapter-scoped in a way a name isn't - "the boy"
may mean someone else two chapters later. An idea considered and not built:
scan chapter text once for naming constructions and take *whatever* pair they
name, which is O(text) rather than O(pairs²) and would catch epithets. It was
dropped because "Will, known as the Ranger's apprentice" yields the pair
(Will, Ranger) from a sentence that asserts nothing of the kind; the string
relationship is what currently makes the text evidence trustworthy.

## The residue rule (`_residue_variant_pairs`)

> **The rule itself now lives in `bookrag.names`** — see
> `context/src/bookrag/names.py.md` for the mechanism, the guards and the
> scoring. This section covers only what the `doctor` path does with it. The
> same core also runs at *ingest* (`cli.auto_link_title_variants`), where it
> links without asking; the two differ in their final guard because the
> evidence available differs, and in the ratio because the cost of being wrong
> differs.

Build-order item **02c(i)+(ii)+(vi)**: a character fragmented across a title,
a clan prefix and a bare name. Reported case - *Reverend Insanity*'s
protagonist is `Fang Yuan`, `Gu Yue Fang Yuan`, `Lord`/`Elder Fang Yuan` and
about thirty surface forms in total, of which the three rules above reached
**one**, and only because `lord` happens to sit in `_TITLES`.

**Do not classify the prefix; test what is left behind.** Three classifiers
were built and all three failed - the best read invented name-parts
(`Northern`, `Yellow`, `Blood`, `Star`) as titles and put the real ranks
`Elder` and `Senior` in the reject bucket. Ordinary-English-ness cannot
separate a rank from an invented name-part, because a book's invented
vocabulary is English-shaped. So strip a leading token only when the
remainder is a better-attested name in the same book:

```
link "P R" -> R iff
  freq(R) >= 100  and  freq(R) >= 5 x freq(P R)
  freq(P R) >= 10                  # the decorated form is real, not a hapax
  R stands on its own              # guards A and B, both required
```

Frequencies are **maximal runs of capitalised words** in that book's own
prose, so `Fang Yuan` counts only its bare sightings and `Lord Fang Yuan` is
counted separately rather than folded into it.

**Guards A and B are both required, and that was measured.** A residue of two
or more tokens is already name-shaped and needs neither. For a single token:
(A) the book must not use the word in lowercase 25+ times, and (B) the bare
form must outnumber the token's use inside longer names. On Reverend Insanity
A alone gives 355 links and strips surnames and category nouns (`Moonlight Gu`
→ `Gu`, `Liu Wen Wu` → `Wu`); B alone gives 221 and strips capitalised
pronouns (`Chi Qu You` → `You`, `Qin Bai He` → `He`). Together: 203 links, 2
wrong.

**Scored by hand over all 8 books: 240 links, 231 correct, 96.3%**, guards
fixed before scoring rather than after.

### Three things that fall out of testing the residue

- **No wordlist, and not eastern-specific.** Over the other seven books it
  proposes 37 links and stays silent on both nonfiction titles, finding
  `Magister Nevery`, `Underlord Crowe`, `Captain Ahab`, `The Aes Sedai` -
  titles no closed list can hold *because the book invented them*.
  `Magister` is the same word `ingest/vocatives.py` false-positived on.
- **The ambiguity veto dissolves.** `_fuller_name_pairs` refuses a short name
  that sits inside more than one longer one; each decorated form is tested
  against the bare name independently, so four decorated forms give four
  links. More titles means more evidence, which inverts 02c(ii).
- **Sentence-initial words stop being a trap.** 181 distinct capitalised forms
  precede `Fang Yuan` and the commonest are `But` (741), `If` (332), `When`
  (191). All link back to `Fang Yuan`, which is correct for them - the
  prefix's identity never has to be decided.

### Two changes made while porting it, both measured

- **The cross-book half of guard A was dropped, and precision went up.** As
  scored, a residue counted as an ordinary English word when it was lowercase
  25+ times in the book *and* appeared in 6 of the library's 8 books. That
  cannot ship: a three-book library can never satisfy it, so the rule would
  silently degrade to guard B alone. Dropping it loses 3 links, of which 2
  were scored errors - **237 links, 230 correct, 97.0%** at the 5x ratio, and
  **250 / 240 / 96.0%** at the 3x this path now uses (see `names.py`).
- **Characters only, which the scoring could not have told us.** The
  hand-scoring ran over raw text and had no entity types in it. Sorting the
  surviving links by type afterwards, all 7 remaining errors are things rather
  than people (`Blue Elixir` → `Elixir`, `Red Genome` → `Genome`, `Mount
  Augustus` → `Augustus`), and every correct non-character link but one is a
  determiner strip (`The Wargals` → `Wargals`, `The Ogier` → `Ogier`) that
  `match_key` already unifies, so `detect_duplicate_entities` reports it
  either way. The restriction removes the whole observed error class at a cost
  of approximately nothing - a very different trade from the rejected
  productivity guard below.

**The rejected guard, recorded so it is not revived.** Requiring the prefix to
be *productive* - to decorate several different identities - removes 5 of the
9 errors and costs 58 links (240→182 at productivity ≥2), taking precision
from 96.3% to 97.8% by losing roughly 53 correct links. Same posture as the
prefix heuristic under rank 02.

**This path uses the looser 3x ratio, and that was a decision about cost, not
evidence.** The 13 links it adds were hand-scored afterwards: 10 correct, 3
wrong. A wrong *proposal* costs one keystroke to decline, so the extra recall
is worth it here; the ingest path keeps 5x because a wrong *merge* is applied
silently. See `names.py`'s context doc for the full table.

**What it does not reach**, so the phase-order question on 02c is unchanged:
every link is a decorated form of a name already present. It reaches none of
the assumed identities (`Hei Lou Lan`, `Wu Shuai`, `Qi Sea Ancestor`), which
share no tokens with `Fang Yuan` - that is 02c(iii) and (iv)'s work. This
addresses the **0.67%** of the protagonist's mentions that carry a title or
clan prefix, offline, with no schema change and no re-extraction.

**What it adds over `_fuller_name_pairs` at entity level**, which is narrower
than the raw-text link count suggests and worth not re-deriving: a *single*
decorated form is already linked by containment. The new reach is (1) the
multi-decorated-form case the ambiguity veto refuses, and (2) frequency
evidence in place of pure spelling. Every test for this rule therefore uses
two decorated forms - a two-entity fixture passes with the rule deleted.

**Measured end to end on real prose**, with an entity set synthesised from
forms verified present in `chapters.jsonl` (the library has no extracted
entities for this book). Before: `Fang Yuan` = `Lord Fang Yuan`, one pair,
and `Fang Zheng` nothing at all. After: `Fang Yuan` clusters with `Lord`,
`Elder` and `Gu Yue Fang Yuan`, and `Fang Zheng` gets his own three-form
cluster **without** being fused into Fang Yuan's despite sharing the `Gu Yue`
prefix. `Demon King Fang Yuan`, which occurs once in 2,360 chapters, is
correctly left out.

**Cost.** Chapters are read only when some entity's name is a proper suffix of
another's in the same book, so the common case costs nothing; a real
`bookrag doctor` run on the current library still takes 0.8s. The largest book
in the corpus (2,360 chapters) scans in under two seconds when it does fire.

**Propose-only, like its three siblings** - reported by `bookrag doctor` and
applied by `--merge-name-variants`, never by `--fix`. The known failure shape
ships documented rather than guarded against, and the transfer hazard 02c
records is untouched: `Wolf King` names Chang Shan Yin before chapter 432 and
Fang Yuan after, and nothing here is chapter-scoped. That is 02c(iii).

## `link_names` / `unlink_names`
- `link_names(book_id, names, root, epithets, reason) -> LinkResult` — declares
  a name set to be one character. **Before extraction** it seeds, so the split
  never forms; **after** it merges whatever entities already hold those names,
  reusing `merge_entities`, because a real extraction costs hours and arriving
  late must not mean starting over. Uses `resolve.seed_alias_group` for the
  create-or-extend path so it and `extract_book` cannot disagree about what a
  linked entity looks like. `names` and `epithets` stay separate all the way
  down - see the two-list rule in `extract/resolve.py`'s context doc.
- `unlink_names(book_id, root) -> list[str]` — the escape hatch that makes
  automatic linking acceptable. A heuristic will sometimes be wrong, and
  "wrong and permanent" is a different proposition from "wrong and one command
  away". **Separates names, never facts**: already-written facts keep the
  `entity_id` they were given, and only a re-extraction can re-decide that.
  `entity_name` on new fact records (see `extract/pipeline.py`) is what would
  make a real splitter possible; it is not built yet.
