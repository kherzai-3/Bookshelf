---
source: tests/test_prompts.py
last_synced: 2026-09-14T14:10:38Z
source_hash: 600e559ac3f42e15121583a1da91b19ca4a2f805
---

## Purpose
Guards the prompt text this project actually ships to a model. These are
content tests rather than behaviour tests, and they exist because of a
failure no other test in this suite can see: **a model faithfully following
an instruction that was itself wrong.**

The bug they were written for: a user cloned the repo, ran `install.py`,
ingested a book of their own, and got back a fact saying the protagonist
*"was nervous about the Choosing Day"* - a Ranger's Apprentice plot point,
from a book they never ingested. `data/` is gitignored, so their clone held
no books at all; the sentence was shipped verbatim inside
`providers/prompts.py` as a style example, and a 7B model copied it. Every
existing test passed throughout, because the pipeline was working exactly as
written.

## Public Interface
Test functions only - no helpers exported.

- `test_prompt_contains_no_real_book_content` - the core guard. Parametrized
  over all four shipped prompts (`EXTRACTION_SYSTEM_PROMPTS` +
  `ANSWER_SYSTEM_PROMPTS`) × `_REAL_BOOK_CONTENT`, so a new prompt added to
  either dict is covered automatically.
- `test_built_messages_contain_no_real_book_content` - the same rule applied
  to `build_user_message`/`build_answer_user_message`, which wrap
  caller-supplied text but must contribute no book content of their own.
- `test_extraction_prompt_labels_its_example_as_illustrative` - asserts both
  extraction prompts still carry the "ILLUSTRATION OF THE OUTPUT FORMAT
  ONLY" / "must never appear in your output" framing.
- `test_extraction_prompt_example_facts_carry_a_when_field` - every example
  fact object must have a `when`, since
  `parsing.extraction_response_schema()` marks it required.

## Key Decisions
- **`_REAL_BOOK_CONTENT` is a denylist of real proper nouns, not a general
  heuristic.** Every entry was present in a shipped prompt at some point:
  Ranger's Apprentice (`Choosing Day`, `Halt`, `Morgarath`, `Celtica`,
  `oakleaf`, `Battleschool`, ...), Atomic Habits (`James Clear`, `habit
  stacking`), Moby Dick (`Ishmael`, `Ahab`, `Pequod`). A denylist cannot
  catch a *new* real book's content, and is not pretending to - it pins the
  specific regression and documents the rule for the next person editing a
  prompt. The failure message says what to do instead ("use invented names
  and details in prompt examples") rather than just reporting a mismatch.
- **Worked examples are kept, not deleted.** They measurably improve a small
  local model's output, and the fix was to rewrite them with invented
  content - which also makes any future leak *always wrong about a book*
  rather than plausibly right about a different one, and therefore catchable
  by `extract/pipeline.py`'s grounding check.
- **Matching is case-insensitive substring**, deliberately loose: this is a
  test over ~4KB of static prompt text with no performance concern, and a
  false positive here is cheap to resolve while a false negative is the
  entire bug.
- The `when`-field test parses the prompt by splitting on `"entity_name"`
  rather than JSON-decoding the example. The examples are embedded in prose
  with line-continuation backslashes and are not independently parseable;
  splitting on the key that starts every fact object is the cheapest thing
  that actually catches the real defect (the nonfiction example omitted
  `when` on every fact, contradicting the schema the same request enforces).

## Dependencies
- Internal: `bookrag.providers.prompts`
- External: `pytest`

## Open Questions / TODOs
- The denylist only covers books this project has been developed against.
  If a prompt example is ever rewritten again, the rule to follow is the one
  in `providers/prompts.py`'s context doc (invented content only), not
  "avoid these specific strings".
