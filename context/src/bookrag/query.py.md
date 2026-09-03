---
source: src/bookrag/query.py
last_synced: 2026-09-03T00:00:00Z
source_hash: 8d8cf9ba3798d07b9ec6ba347f0222898c0e2061
---

## Purpose
The spoiler-safety primitive: the one function any query/chat layer must go
through to avoid leaking facts from beyond a given reading position. This is
the actual point of the whole project - everything else (ingestion,
extraction) exists to feed this. Also renders those facts into the plain-text
context `cli.py`'s `chat` command hands to a provider's `answer_question`.

## Public Interface
- `Fact(book_id, entity_id, chapter_index, category, statement)`
- `facts_as_of(book_id: str, chapter_index: int, root: Path | None = None)
  -> list[Fact]` — never returns a fact past `(book_id, chapter_index)` in
  series reading order.
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
- Deliberately just a positional filter over `facts.jsonl` today, not a
  semantic/RAG retrieval step - that's the next layer, built on top of this.
- `format_context` never discards or dedupes facts, even ones that later
  contradict an earlier one for the same entity (e.g. an early chapter says
  a status hasn't happened yet, a later one says it has) - a coarse "keep
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
  `bookrag.extract.resolve.load_entities`
