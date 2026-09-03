---
source: src/bookrag/providers/prompts.py
last_synced: 2026-09-03T00:00:00Z
source_hash: cf815be99948804ed61faee32a5b1769d2ca79db
---

## Purpose
The shared prompts every provider uses for each task - factored out so
providers are judged by `eval.py` (extraction) or compared (question
answering) on the model's output, not on subtly different wording of the
instructions.

## Public Interface
- `EXTRACTION_SYSTEM_PROMPT: str` — a one-line definition per category, an
  explicit self-containment rule for `statement`, an anti-fabrication +
  non-narrative-content rule, and one worked example. Response shape is
  `{"facts": [...]}`, matching `parsing.extraction_response_schema()`.
- `build_user_message(chapter_text: str, known_entities: list[str]) -> str` —
  frames `known_entities` as "use these exact names for someone already
  introduced," not "don't restate" (see Key Decisions).
- `ANSWER_SYSTEM_PROMPT: str` — instructs the model to answer only from the
  facts it's given and never from outside knowledge of the book, since
  outside knowledge could leak spoilers past the reader's current chapter.
- `build_answer_user_message(question: str, context: str) -> str`

## Key Decisions
- `EXTRACTION_SYSTEM_PROMPT` no longer says "only report new or changed
  facts" - dropped deliberately. It was unenforceable (the model only ever
  receives prior entity *names* via `known_entities`, never prior fact
  *content*, so it had no way to judge novelty) and is now unnecessary,
  since `query.format_context`/`ANSWER_SYSTEM_PROMPT` already resolve
  cross-chapter recency at read time. Removing it frees a small model's
  limited instruction-following budget for what actually matters: clear
  categorization and self-contained statements.
- Per-category definitions were added specifically because `status` was the
  rarest, least useful category in real extracted data (5/73 facts in a
  real run, none capturing an actual milestone) - the prompt now explicitly
  reserves it for "a concrete, factual change in role, rank, allegiance, or
  life-condition," not fleeting reactions.
- The self-containment rule and worked example exist because real extracted
  statements were frequently vague, pronoun-dependent fragments (e.g. "he
  knew it all too well, in fact...", "totally exhausted") - a small model
  benefits disproportionately from one concrete example over prose rules
  alone.
- The anti-fabrication + "return `{"facts": []}` for non-narrative text"
  rule exists because a real extraction against a bare table-of-contents
  fragment (zero narrative content) fabricated an entire character with a
  full backstory who never appears anywhere in the book. This is a
  prompt-side defense; `extract.pipeline.MIN_NARRATIVE_WORDS` is the
  code-side one for the shortest fragments (see that file's context doc) -
  a longer non-narrative fragment (a table of contents, an author bio) can
  be too long for the word-count floor to catch, which is why both exist.
- `ANSWER_SYSTEM_PROMPT` explicitly tells the model to say "I don't have
  enough information about that yet" rather than guess when the provided
  `context` is insufficient - guessing risks fabricating (or worse,
  correctly guessing and spoiling) something not yet in the reader's
  spoiler-safe fact set.
- `ANSWER_SYSTEM_PROMPT` also documents `query.format_context`'s grouped/
  `[ch N]`-tagged shape and tells the model to prefer the later chapter's
  fact when two facts in the same category for the same entity genuinely
  conflict, while treating different categories (or different specifics
  within one) as cumulative, not competing. This is the answer-time half of
  fixing cross-chapter contradictions (e.g. a status that changes) - the
  catalog itself never dedupes or discards facts (see `query.py`'s context
  doc for why), so recency resolution has to happen here, in how the model
  is told to read the context it's given.
