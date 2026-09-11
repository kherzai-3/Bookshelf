---
source: src/bookrag/query.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 49dd36059f8fcbca97c40556ddc281403d64663d
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
  None = None) -> list[Fact]` — three tiers, each a fallback for the one
  before: (1) filter to the entities the question names (see Key Decisions);
  (2) if it names none, `_facts_matching_question_text` matches the
  question's distinctive words against the *statements*; (3) if that also
  finds nothing, return every fact unchanged, preserving the original
  guarantee. Runs between `facts_as_of` and `format_context`.
- `_facts_matching_question_text(question, facts) -> list[Fact]` /
  `_content_words(text) -> set[str]` / `_MAX_STATEMENT_MATCHES = 80` — the
  statement-matching tier. Words appearing in more than a tenth of the
  statements are treated as carrying no topical signal; the rest are scored
  by rarity (`1/document_frequency`), ranked, and capped.
- `format_context(facts: list[Fact], root: Path | None = None,
  content_type: str = "fiction") -> str` — groups facts by entity, and
  within an entity splits them into the two kinds that must be *read*
  differently (see `parsing.OCCURRENCE_CATEGORIES`):
  - **"What happened, in order"** — occurrence categories, rendered as one
    chronological sequence with the category inline
    (`"[ch 34] (status) ..."`). Separate moments; a later line never
    corrects an earlier one.
  - **"Standing description"** — everything else, keeping the older
    per-category grouping, where a later line legitimately supersedes an
    earlier one.
  Each block's header states that rule in plain language, because a small
  local model follows visible structure far more reliably than a paragraph
  of prompt instructions - the same reasoning behind schema-constraining
  extraction rather than asking nicely. Entity names resolve via the global
  registry (`extract.resolve.load_entities`), falling back to the raw
  `entity_id`. `content_type` selects the occurrence set; nonfiction's is
  empty, so a nonfiction book renders entirely as standing description
  (its old shape). Empty `facts` renders as `""`, which providers treat as
  "no information yet".

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
- **No-match ultimately falls back to every fact, unfiltered** - a
  general/topical question naming no specific entity (e.g. "what has happened
  so far?") must not be wrongly narrowed to nothing. Statement matching (see
  below) now sits *between* entity matching and this fallback, so the
  whole-book dump is reached far less often, but it remains the last tier and
  a sufficiently broad question can still overflow a small context window -
  `OllamaProvider`'s raised `DEFAULT_NUM_CTX` (16384) is the safety net for
  that remaining case, not a full fix on its own.
- Verified against real Ollama output, not just unit tests: after this and
  the entity-deduplication work (`library.merge_entities`, run once
  against the real library), "What does Halt look like?" changed from
  "not mentioned in the novel" to a real answer, and "Tell me about the
  Wargals" went from fragmented/overflowing context to one complete,
  well-organized answer covering appearance, behavior, and relationships.
- **The occurrence/standing split is the structural half of a real
  wrong-answer fix.** A character wounded by monsters in ch.34 and an
  unrelated report of his death in ch.66 - both `status` - were fused by the
  answer prompt's blanket "trust the later chapter" rule into "he died
  fighting the monsters." That rule is right for a standing property and
  actively wrong for occurrences. Verified against the frozen pre-restart
  fixture (the only place the repro still exists, since the fresh
  qwen2.5:7b-instruct extraction doesn't reproduce the hallucinated death
  facts): the same question that previously concluded "killed during the
  fight with the Kalkara" now keeps the two occasions distinct and
  attributes each correctly. Worth being precise about the limit - that old
  data asserts "Halt was killed" three separate times, so the answer is
  still wrong *about the death*; what the fix removes is the **fusion** of
  two unrelated events, not the underlying hallucination. An answer-layer
  change cannot rescue false data, only stop compounding it.
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

## Statement matching (the third retrieval tier)
- **Why it exists: entity-name matching only closed half the overflow bug.**
  `select_relevant_facts` originally matched entity names and, failing that,
  returned everything. On the real 1248-fact library, 3 of 6 realistic
  questions took that fallback - and the resulting context measured ~34,500
  tokens against a 16,384 `num_ctx`, i.e. **2.1x over, silently truncated.**
  Questions naming an event rather than a cataloged entity ("what happened at
  the choosing ceremony?", "the battle at Hackham Heath") are the common
  shape that misses. Statement matching converts those from a truncated
  whole-book dump into a tight subset (measured 8 and 40 facts respectively).
- **Rarity is computed over the passed-in `facts`, never the whole book.**
  Not an optimization - a word's rarity derived from chapters the reader
  hasn't reached is a value computed from hidden data, and deriving anything
  from the unfiltered set is how a filter leaks what it removed. Since the
  caller only ever passes an already-spoiler-filtered list, computing here is
  correct by construction.
- **Ranked and capped, not gated on a hit count.** Requiring two shared rare
  words was tried first and failed on a real question: a reader says "choosing
  ceremony", the book says "Choosing Day" - one word in common, so a hit-count
  rule discarded precisely the topic it was meant to find. Scoring tolerates
  the phrasing mismatch, and `_MAX_STATEMENT_MATCHES` does the bounding the
  hit count was really there for. Note the cap only engages on large
  libraries: a word must appear 80+ times while staying under the one-in-ten
  ceiling, so it needs 800+ facts to bite.
- **Deliberately still not semantic search.** A question with no lexical
  overlap at all ("who are the antagonists?") still falls through to the
  whole-book fallback - correctly, since guessing would be worse. That case
  is what the deferred embedding work in README's Future ideas is for.
