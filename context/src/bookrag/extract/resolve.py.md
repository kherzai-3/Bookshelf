---
source: src/bookrag/extract/resolve.py
last_synced: 2026-09-17T14:28:47Z
source_hash: f9ffaedacbae87e23b6daed0fa9b67c3c63c2ca6
---

## Purpose
Resolves a raw extracted `entity_name` string to a stable `entity_id`
against the global entity registry (`data/library/entities.json`), and manages that
registry's load/save.

## Public Interface
- `entities_path(root=None) -> Path` — `<root>/entities.json`.
- `load_entities(root=None) -> dict` — `{"entities": []}` if the file
  doesn't exist yet.
- `save_entities(entities: dict, root=None) -> None`
- `resolve_entity(name: str, entity_type: str, book_id: str, entities: dict)
  -> str` — **mutates `entities` in place** (adds a new entry, or records
  `book_id` against an existing match) and returns the resolved
  `entity_id`. Matches via `match_key` (see Key Decisions), not raw
  string equality.
- `group_name_variants(names: list[str]) -> list[list[str]]` — partitions names
  into groups that plausibly name one person, by `looks_like_a_name_variant`.
  Input order preserved; a name with no partner comes back alone.

  **Exists because pairing is not grouping, and the gap was a live bug.**
  `looks_like_a_name_variant` answers a question about a *pair*, so a caller
  that keeps every name having any partner and treats the survivors as one set
  fuses unrelated people: `Conn`/`Connwaer` plus `Row`/`Rowena` came back as a
  single four-name character. `ingest.vocatives.auto_link_plan` did exactly
  that and links **without asking, at ingest**, so a two-narrator book had its
  narrators silently declared one person in `entities.json`. It now requires
  exactly one group of 2+ and links nothing otherwise.

  `library._connected_clusters` does the same shape of work over
  `(a, b, reason)` triples and threads the reasons through. The two could
  converge, but reusing that signature here would mean inventing reasons only
  to discard them.
- `prune_book_from_entities(entities: dict, book_id: str) -> tuple[int, int]`
  — **mutates `entities` in place**: removes `book_id` from every entity's
  `book_ids`, dropping any entity this leaves with none. Returns
  `(entities_pruned, entities_deleted)`. Added for `library.remove_book`/
  `bookrag doctor`'s cleanup - the inverse operation of `resolve_entity`
  adding a `book_id`.

## Key Decisions
- **No real fuzzy/semantic coreference** - "the old man" will not
  automatically link to "Ishmael". Documented as a known limitation
  (README's Known Limitations) rather than solved here - same posture as
  the epub/pdf ingestion heuristics: ship something reasonable, make the
  gap visible, improve iteratively. Aliases can be added to
  `entities.json` by hand today.
- **`match_key(name)` adds light, comparison-only normalization** (strip a
  leading "the ", strip a trailing "s") on top of the case-insensitive
  exact match, used for both `canonical_name` and every alias.
  Deliberately narrow, not real fuzzy matching (no edit-distance/
  similarity library) - real bug found and fixed by this: a single
  creature ("Wargal(s)" in a real book) had fragmented into 5 entities
  across name variants ("Wargals"/"The Wargals") *and* entity_types
  (see the type-drift item below, and `extract/pipeline.py`'s
  `known_entity_types` for the other half of that fix). A broader
  similarity library was deliberately not added here - real risk of
  false-positive merges (two genuinely different names colliding) without
  much more careful thresholding/testing than this narrow, high-confidence
  rule needs.
- Matching is scoped by `entity_type` - a character and a setting with the
  same name (e.g. "Nantucket" the place vs. a character nicknamed
  "Nantucket") resolve to two separate entities.
- `entity_id` format is `f"{entity_type}-{uuid4().hex[:8]}"` - readable
  prefix, no collision-handling needed given the fixed-length random suffix.

## Data Contracts
- Entity record: `{entity_id, canonical_name, type, aliases: [str],
  book_ids: [str]}`.


## The two-list rule (`aliases` vs `epithets`)

An entity carries **two** name lists, and the split is a safety property, not
tidiness. They exist because the two consumers match differently:

| Consumer | Match | Reads |
|---|---|---|
| `extract.resolve.resolve_entity` | `name_key == match_key(x)`, **exact** | `aliases` **and** `epithets` |
| `query._name_matches_question` | `name_lc in question_lc`, **substring** | `aliases` only |

So an epithet of "boy" absorbs a fact the model filed under "boy" and can
never reach for a different boy - but if it were substring-matched against a
question, every question containing that word would retrieve this character.

**This is the larger half of the win, not a side case.** On the real reported
book the epithets outweigh the names: boy 495 references in the text, thief
136, gutterboy 100, against Conn 344 and Connwaer 162. Measured end to end
after auto-linking, `entity_name` on the fact records shows 28 facts arriving
as "Boy" and 11 as "Thief" that would otherwise have fragmented.

Verified both directions on a real library copy: "Tell me about Connwaer"
retrieves the character (alias), "Who is the boy in the kitchen?" and
"describe the thief" do **not** (epithets).

**Adding `epithets` to `query.select_relevant_facts`'s candidate list is the
one change that silently undoes all of this.**

## Dependencies
- Internal: `bookrag.storage.library_root`

## Open Questions / TODOs
- **`resolve_entity` matches globally across the *entire* library, not
  scoped to a series or otherwise related books** - noticed while building
  `library.py`. Two completely unrelated books that both introduce a
  character of the same name and `entity_type` (e.g. two different novels
  each with a "Will") will silently resolve to the *same* `entity_id`,
  because matching only checks `(name, entity_type)`, never whether the
  books are actually related. This is intentional for the series case
  (`storage.series_reading_order` relies on facts about the same character
  accumulating across sequential books) but was never scoped to *only* the
  series case - it currently applies library-wide. Not a spoiler-safety bug
  (each book's own `facts.jsonl` stays correctly scoped by `chapter_index`
  regardless), but it does mean `entities.json`'s registry can conflate two
  unrelated characters' identities. No real collision has been observed
  yet (the current library's books don't share character names) - flagged
  here so it's not re-discovered from scratch if one ever does.

## Identity is scoped to a series, not to the whole library

`entities.json` is a single global file, but that is storage, not identity.
Before this, `resolve_entity`'s match loop ran over **every entity from every
book ever ingested**, keyed only on `(match_key(name), entity_type)` - no
book or series filter anywhere. `book_id` was used only *after* a match, to
append to `book_ids`.

So any two unrelated books sharing a common name became one entity. Observed
live in a real four-book library, not hypothetically:

| entity | books merged |
|---|---|
| `George` (character) | Ranger's Apprentice + Atomic Habits |
| `Michael` (character) | Ranger's Apprentice + Moby Dick |
| `Power` (concept) | Finite and Infinite Games + Atomic Habits |
| `Prediction` (concept) | Finite and Infinite Games + Atomic Habits |

**Scope of the damage, stated precisely.** This never leaked facts between
books: `query.facts_as_of` reads per-book `facts.jsonl` files within
`series_reading_order`, so Moby Dick's facts about its Michael were never
loaded into a Ranger's Apprentice conversation. What it corrupted is the
registry's answer to *"who is this and which books do they appear in"* -
`canonical_name` and `type` are first-come, so a later book's entity displays
under an earlier unrelated book's spelling, and `book_ids` claims appearances
that never happened. That field is exactly what any future cross-book or
series-catalog feature would be built on.

`match_key` widens the collision surface further (it strips a leading "the"
and a trailing "s" for matching), and before this it did so against the whole
library rather than one series.

**The fix**: `resolve_entity(..., scope=[book_ids])` matches only entities
already claimed by a book in scope. `extract.pipeline` passes
`series_reading_order(book_id, root)` - computed once and reused for the
`known_names`/`known_types` seeds too, since all three must agree or the
pipeline contradicts itself (telling the provider a name is known while
resolving it to a fresh entity).

**Why the default scope is the narrow one.** `scope=None` means `[book_id]`,
i.e. no sharing. The two failure directions are not symmetric:
- too narrow → an entity duplicates *within* a series: visible, and
  repairable by `bookrag doctor`'s existing merge;
- too wide → two unrelated books' characters silently fuse into one record:
  invisible, and not repairable by a merge tool, because merging is the
  operation that caused it.

A caller who forgets to pass a scope should get the recoverable failure.

**Does not fix existing data.** Entities already merged stay merged - the
four above survived a full re-extraction, because a re-run resolves against
the same registry. They need a `doctor` repair (a split, which doctor does
not currently offer) or a rebuild of the registry.
