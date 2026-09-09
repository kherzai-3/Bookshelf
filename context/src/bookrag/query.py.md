---
source: src/bookrag/query.py
last_synced: 2026-09-09T00:00:00Z
source_hash: b88f0b78a3b2bbc5f2bd2a345a2a3395977414ad
---

## Purpose
The spoiler-safety primitive: the one function any query/chat layer must go
through to avoid leaking facts from beyond a given reading position. This is
the actual point of the whole project - everything else (ingestion,
extraction) exists to feed this. Also filters those facts down to what a
specific question seems to be about, and renders the result into the
plain-text context `cli.py`'s `chat` command hands to a provider's
`answer_question`.

## Public Interface
- `Fact(book_id, entity_id, chapter_index, category, statement)`
- `facts_as_of(book_id: str, chapter_index: int, root: Path | None = None)
  -> list[Fact]` — never returns a fact past `(book_id, chapter_index)` in
  series reading order.
- `select_relevant_facts(question: str, facts: list[Fact], root: Path |
  None = None) -> list[Fact]` — filters to just the entities a question
  appears to name (see Key Decisions for the matching approach and why);
  returns every fact unchanged if nothing matches at all. Meant to run
  between `facts_as_of` and `format_context`, not as a replacement for
  either.
- `format_context(facts: list[Fact], root: Path | None = None) -> str` —
  groups facts by entity, then by category, each line tagged
  `"[ch N] statement"` and sorted chronologically within its group; entity
  names resolved via the global entity registry (`extract.resolve.load_entities`),
  falling back to the raw `entity_id` if unresolved. Empty `facts` renders
  as `""`, which providers treat as "no information yet" rather than a
  valid-but-empty context.

## Key Decisions
- Uses `series_reading_order(book_id)` (see `storage.py`): every **earlier**
  book in the series is treated as entirely "in the past" (all of its
  facts are included, regardless of chapter), and only the book actually
  being queried is chapter-limited. A standalone book's reading order is
  just itself.
- Tested explicitly for the failure mode that matters most:
  `tests/test_query.py::test_facts_as_of_does_not_leak_a_later_book_in_the_series`
  and `..._never_returns_a_fact_past_the_given_chapter` - these are the
  actual spoiler-safety guarantee, not incidental coverage.
- **`select_relevant_facts` is a cheap, dependency-free retrieval layer,
  not real semantic/embedding search** (see README's Future ideas for
  that, still not built). Matching: case-insensitive substring against an
  entity's canonical name/aliases, `extract.resolve.match_key`
  normalization (so a question about "Wargal" matches an entity actually
  named "Wargals"/"The Wargals" - `match_key` handles the direction plain
  substring can't, e.g. "The Wargals" isn't a substring of a question
  asking about "wargal"), then `difflib.SequenceMatcher` (stdlib, no new
  dependency) for single-word names only as a last-resort fuzzy fallback.
  Real motivating problem this fixes, confirmed on the real
  ranger-s-apprentice-1-2-bindup library: before this existed, `format_context`
  had no cap of any kind (see below) and a full book's assembled context
  measured ~26,000-30,000 tokens by its final chapters - several times
  `OllamaProvider`'s context window (see that file's context doc) - so most
  of it was being silently dropped by the runtime on every single chat
  call, independent of what was asked. Filtering down to just the named
  entity's facts fixes this by construction (far less content sent), not
  just the "can't find it by exact string" complaint that originally
  motivated it.
- **No-match falls back to every fact, unfiltered** - a general/topical
  question naming no specific entity (e.g. "what has happened so far?")
  must not be wrongly narrowed to nothing. This means a sufficiently broad
  question can still overflow a small context window - `OllamaProvider`'s
  raised `DEFAULT_NUM_CTX` (16384) is the safety net for exactly this
  remaining case, not a full fix on its own.
- Verified against real Ollama output, not just unit tests: after this and
  the entity-deduplication work (`library.merge_entities`, run once
  against the real library), "What does Halt look like?" changed from
  "not mentioned in the novel" to a real answer, and "Tell me about the
  Wargals" went from fragmented/overflowing context to one complete,
  well-organized answer covering appearance, behavior, and relationships.
- `format_context` itself still never discards or dedupes facts (that
  hasn't changed - `select_relevant_facts` is a separate step *before* it,
  not a change to what it does with whatever it's given), even ones that
  later contradict an earlier one for the same entity (e.g. an early
  chapter says a status hasn't happened yet, a later one says it has) - a
  coarse "keep
  only the latest fact per (entity, category)" rule was considered and
  rejected, since `status`/`relationship` are not single-valued (a
  character can have several simultaneous status facts, or relationships
  with several people, all sharing one category) and pruning by category
  alone would silently delete other, still-true facts. Instead, chronology
  is made explicit (`[ch N]` tags, sorted, grouped by entity/category) and
  `providers.prompts.ANSWER_SYSTEM_PROMPT` instructs the answering model to
  prefer the later chapter's fact when two in the same category genuinely
  conflict - resolution happens at read/answer time, not by mutating the
  catalog.

## Dependencies
- Internal: `bookrag.storage` (`library_root`, `series_reading_order`),
  `bookrag.extract.resolve` (`load_entities`, `match_key`)
- External: `difflib` (stdlib) for `select_relevant_facts`'s fuzzy fallback
