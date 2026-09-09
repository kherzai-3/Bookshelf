---
source: src/bookrag/providers/prompts.py
last_synced: 2026-09-09T00:00:00Z
source_hash: e4247babbfee0d5c2a0e61a18580b0baf5606bcd
---

## Purpose
The shared prompts every provider uses for each task - factored out so
providers are judged by `eval.py` (extraction) or compared (question
answering) on the model's output, not on subtly different wording of the
instructions. Now two parallel pairs (fiction/nonfiction), selected by a
book's `content_type` (see `storage.py`/`extract/pipeline.py`).

## Public Interface
- `EXTRACTION_SYSTEM_PROMPT: str` — the fiction extraction prompt: a
  one-line definition per category, an explicit self-containment rule for
  `statement`, an anti-fabrication + non-narrative-content rule, and one
  worked example. Response shape is `{"facts": [...]}`, matching
  `parsing.extraction_response_schema()`.
- `EXTRACTION_SYSTEM_PROMPT_NONFICTION: str` — a full parallel prompt (not
  an interpolated template), for `parsing.ALLOWED_CATEGORIES_NONFICTION`/
  `ALLOWED_ENTITY_TYPES_NONFICTION`'s taxonomy - its own worked example
  ("habit stacking", not Will/Halt), and its "return `{"facts": []}`"
  condition is framed around front/back matter (copyright notice,
  dedication, index, acknowledgments) rather than "not part of the story's
  narrative" - the fiction wording would misfire on a nonfiction book's
  *entire* body, which is never narrative in that sense.
- `EXTRACTION_SYSTEM_PROMPTS: dict[str, str]` — `{"fiction": ...,
  "nonfiction": ...}`, so providers do a simple `[content_type]` lookup
  rather than branching logic duplicated in each implementation.
- `build_user_message(chapter_text: str, known_entities: list[str],
  known_entity_types: dict[str, str] | None = None) -> str` — frames
  `known_entities` as "use these exact names for someone already
  introduced," not "don't restate" (see Key Decisions). When
  `known_entity_types` is given, each known name is rendered with its
  established type inline (e.g. "Wargals (setting)") and the instruction
  also says to keep the same type, not just the same name - see Key
  Decisions for why. Shared unchanged by both content types - already
  fully mode-agnostic.
- `ANSWER_SYSTEM_PROMPT: str` — the fiction answer prompt: instructs the
  model to answer only from the facts it's given and never from outside
  knowledge of the book, since outside knowledge could leak spoilers past
  the reader's current chapter.
- `ANSWER_SYSTEM_PROMPT_NONFICTION: str` — same structure and mechanism
  explanation, reframed: "spoiler" reads oddly for a self-help book
  (nothing is "spoiled" by an early technique) - reframed around reading
  progress ("a later chapter may define a term... in a way the reader
  hasn't reached yet") instead. `query.format_context`/`facts_as_of` need
  no changes for this - they group purely by `entity_id`/`category` with
  no fiction-specific strings anywhere; only the prose explaining that
  shape to the answering model differs.
- `ANSWER_SYSTEM_PROMPTS: dict[str, str]` — same lookup pattern as
  `EXTRACTION_SYSTEM_PROMPTS`.
- `build_answer_user_message(question: str, context: str) -> str` — shared
  unchanged by both content types.

## Key Decisions
- **`build_user_message` renders each known entity's established type
  alongside its name, when available.** Real root cause found chasing a
  confirmed entity-duplication bug (5 separate "Wargal(s)" entities in one
  real book): `known_entities` previously carried bare name strings only,
  so when the model re-encountered a recurring entity in a later chapter
  it had zero signal that the name was already typed a certain way (e.g.
  `setting`) and re-derived a type from scratch purely from how that
  chapter's sentence read - naturally producing different types for the
  same real-world entity across chapters. `extract.pipeline` now builds a
  name -> type map (from `entities.json`, not guessed) and passes it
  through; `resolve_entity` is still the one place identity is actually
  decided (type-scoped, see its context doc) - this is a soft prompt-side
  hint to reduce future drift, not a hard guarantee.
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
- **`appearance`'s definition explicitly calls out incidental/passing
  mentions, not just dedicated description paragraphs.** Real bug found
  chasing a user-reported "what does Halt look like?" chat failure: the
  real chapter text described Halt's grey-flecked hair and how "the grey
  cloak had concealed a lot about Halt," but only "slim and not at all
  tall" was ever extracted - `appearance` already existed as a category
  and wasn't schema/cap-blocked in that chapter, so this was inconsistent
  model salience, not a missing instruction slot. The worked example was
  updated to match: it now includes an appearance detail mentioned
  mid-action ("Halt's grey cloak shifted... blending into the shadows"),
  not just a dedicated description sentence, since that's the exact shape
  of detail being missed.
- **Two more instructions added together, and needed together**: "never
  report the same fact twice" and "stop once every concretely-stated fact
  is reported - don't invent generic/vague filler just to report more."
  Both found while validating the `appearance` fix above, after
  `parsing.py`'s `maxItems` was raised from 25 to 40 (see that file's
  context doc) to stop cutting off real late-chapter content: with more
  headroom, the same real chapter's real extraction padded out toward the
  new cap two different ways in two separate tests - first the exact same
  status sentence repeated 20+ times verbatim, then (after the
  anti-repetition instruction alone) a run of ~25 technically-distinct but
  vacuous "Will is learning about the importance of being diligent/
  resourceful/adaptable..." statements not grounded in anything specific
  the text actually says. Confirmed both instructions are needed together,
  not just one: only after adding *both*, a real re-run of the same
  chapter naturally stopped at 26 facts (well under the 40 cap) with zero
  padding of either kind, while still fully capturing Halt's appearance
  facts. `extract.pipeline` also added a code-side exact-duplicate filter
  as a second layer, not relying on prompt compliance alone (a small local
  model's instruction-following isn't fully reliable) - see that file's
  context doc for `duplicate_fact_count`. The same anti-repetition/
  anti-filler instructions were added to `EXTRACTION_SYSTEM_PROMPT_NONFICTION`
  too - this is a general small-model generation-behavior issue, not
  specific to fiction content, so nonfiction extraction (Atomic Habits,
  Finite and Infinite Games) is equally exposed to it even though the bug
  that surfaced it was found via a fiction book.
- **Nonfiction gets full parallel prompts, not a parameterized shared
  template.** Considered and rejected: the fiction prompt is fiction-
  specific well beyond its category list ("a single chapter of a novel,"
  a worked example about Will/Halt/the oakleaf, category definitions
  phrased narratively) - interpolating mode-specific vocabulary into one
  shared template would produce a harder-to-tune result than two clean
  prompts. Confirmed the taxonomy mismatch was real, not just
  theoretical, via a checkpoint run (`bookrag eval` against real
  consolidated Atomic Habits chapters, current fiction prompt): "Habits
  Academy" (a real named thing) got the same generic `theme/description`
  treatment as an abstract idea, and an entire chapter about environment
  design for habit formation filed "desk", "phone", "bedroom", "coffee
  shop" as cataloged story `setting`s - see `parsing.py`'s context doc for
  the taxonomy design this drove.
- **Both extraction prompts now instruct splitting a multi-aspect
  sentence/moment into separate, per-category facts rather than filing it
  under only one; both answer prompts now instruct reading across ALL of
  an entity's categories, not just the one whose name matches the
  question's topic.** Real root cause found investigating the same "what
  does Halt look like?" complaint a second time, after the appearance-
  category fix above: a fact schema only allows one category per fact, so
  a sentence like "Halt stroked his beard gravely" - both a personality/
  mood cue AND a physical detail (he has a beard) - could only ever be
  filed one way, silently starving the other question type. The
  extraction-side fix (split into two facts, one worked example added to
  each extraction prompt mirroring this exact real case) only benefits
  future/re-extracted data. The answer-side fix (explicitly told to search
  every category, not just the name-matching one) was verified to work
  against the real, unmodified `ranger-s-apprentice-1-2-bindup` facts.jsonl
  without any re-extraction - but only in 1 of 3 identical real attempts,
  since `answer_question` has no temperature control (see
  `ollama_provider.py`'s context doc, Open Questions) and Ollama's default
  conversational sampling isn't consistent run to run. Both fixes are
  real, verified improvements, but neither is a guarantee - they raise the
  odds a given detail surfaces, not a hard fix.
