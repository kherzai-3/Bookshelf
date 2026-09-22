---
source: tests/helpers.py
last_synced: 2026-09-22T21:20:00Z
source_hash: 77e726293bb23c5cd1e95010212f186bc8fd051d
---

## Purpose
Shared synthetic epub/pdf builders, factored out so `test_epub_loader.py`,
`test_pdf_loader.py`, and `test_cli.py` don't each hand-roll their own sample
book. Both builders set title/author metadata so `extract_metadata` tests
have something real to assert against.

## Public Interface
- `build_sample_epub(path)` / `build_sample_pdf(path)` — two short (~3-word)
  chapters each; fine for ingest/metadata tests, too short to exercise real
  extraction (see `NARRATIVE_PADDING` below).
- `build_narrative_epub(path)` — like `build_sample_epub`, but with two
  chapters padded (via `_bulk_filler`) to ~725 words each, for tests that need
  extraction to actually run against real chapter text, not just ingestion.
  The size is set by `ingest.consolidate`, not by extraction: clearing
  `MIN_NARRATIVE_WORDS` (20) only takes a sentence or two, but anything near
  that would sit under `CONSOLIDATION_MEDIAN_WORDS_THRESHOLD` and get merged
  into a single chapter, breaking every test that assumes two.
- `_bulk_filler(min_words)` — private; repeats the same proper-noun-free,
  `FakeProvider`-safe padding until it clears `min_words`.
- `NARRATIVE_PADDING: str` — a ~20-word block of filler sentences to append
  to a short synthetic `Chapter.text` in extraction/query tests, so it
  clears `MIN_NARRATIVE_WORDS` without `FakeProvider` mistaking any of it
  for a new entity: every sentence starts with one of `FakeProvider`'s own
  pronoun stopwords (It/He/She/They/We), and no other word in it is
  capitalized.
- `build_first_person_epub(path)` — a first-person novel whose dialogue calls
  its narrator "Conn", "Connwaer" and "boy". The only fixture that exercises
  auto-linking at ingest end to end, and the shape `ingest.vocatives` looks
  for: two chapters, each with ~770 words of first-person narration and six
  utterances spoken by a *named* character. Detection on it yields Conn 4/4
  capitalised, Connwaer 4/4, boy 0/4 — so `auto_link_plan` returns
  `(["Conn", "Connwaer"], ["boy"])`.
- `build_titled_character_epub(path)` — a *third-person* novel calling one
  character "Nevery" and "Magister Nevery". The only fixture exercising
  third-person auto-linking (`names.person_link_groups`) at ingest end to end.
  Deliberately not first person, so `ingest.vocatives` stays silent and any
  link can only have come from the residue rule; and "Magister" is
  deliberately absent from `library._TITLES`, since a rank the wordlist
  already contains would prove nothing this feature adds.
- `_I_NARRATE: str` — private; the first-person counterpart to
  `NARRATIVE_PADDING`, proper-noun-free but dense in `I`/`my`/`me` (~16 per 100
  words against `vocatives._FIRST_PERSON_PER_100_WORDS`'s floor of 4.0).
- `build_fragmented_epub(path, fragment_count=40, words_per_fragment=100)` —
  many small, untitled, unheaded spine documents (no `h1`-`h3` markup at
  all), mirroring a real page-scanned Internet-Archive epub (Atomic
  Habits' actual source: one physical page per spine file) - for tests
  that need `ingest.consolidate.should_consolidate` to actually trigger.

## Key Decisions
- `NARRATIVE_PADDING` is appended, never prepended, to a test's real
  sentence(s) - `FakeProvider` splits per sentence and keeps each sentence's
  exact text as its `statement`, so appending preserves the original
  sentence (and any exact-string assertions on it) unchanged while still
  padding the chapter's total word count.
- `build_narrative_epub` exists as a separate builder rather than lengthening
  `build_sample_epub` itself, since the latter is shared by tests
  (`test_epub_loader.py` etc.) that assert its exact short content -
  lengthening it in place would have risked breaking those.
- `build_first_person_epub`'s dialogue puts every name in *trailing* vocative
  position ("You are late, Conn,"), because that is the one position where
  capitalisation is evidence - a leading vocative is sentence-initial and
  capitalised whether it is a name or an epithet. A fixture using leading
  position would make "boy" read as a name and the epithet half of the feature
  would silently not be under test.
- Every utterance in it is attributed to a named speaker rather than "I". That
  is the entire detection signal: in a first-person book an utterance from
  anyone but the narrator is, in a two-hander, addressed *to* the narrator.
- The speaker ("Nevery") is never itself addressed, so it never lands in the
  ambiguous column and never competes with the real aliases.
- `build_titled_character_epub`'s counts are not arbitrary and are the whole
  fixture. The bare name has to clear 100 sightings *and* outnumber the
  decorated form five times over (`names.AUTOLINK_RATIO`), the decorated form
  has to clear 10, and the character has to be caught speaking at least three
  times — without that last part `names.reads_as_a_person` cannot tell him
  from a place, and the link silently does not happen.
