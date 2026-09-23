---
source: tests/test_extraction_pipeline.py
last_synced: 2026-09-23T00:00:00Z
source_hash: b7343ffeecde277ce3081737dcf84da9d16f5e8f
---

## Purpose
Covers `extract.pipeline.extract_book` end-to-end with `FakeProvider`:
correct `facts.jsonl` shape/chapter-scoping, `entities.json` updates, that a
series' second book seeds its known-entities context from the first book
(only genuinely new entities count toward `new_entity_count`), the
per-chapter `ExtractionParseError` tolerance regression (`_FailsOnNthCall`
test double) found running a real 75-chapter book, that `on_chapter_done`
fires once per chapter with `(1-indexed position, total)`, and the
new-entity grounding-check regression (`_FixedResponseProvider` test
double) found in the same real run.

Five tests pin `pipeline._entity_is_grounded`'s matching rules (see that
file's context doc for the measurements behind them). Four are new, added
with the fix for a user-reported hallucination:
- `..._rejects_a_name_that_only_appears_as_an_ordinary_word` - the headline
  case. A name is not grounded by the everyday word it happens to spell:
  `"Will"` must not be accepted by *"he will go to the tower"*. Under the
  old substring check it was, which is why a leaked Ranger's Apprentice
  name reached a user's unrelated book.
- `..._grounding_requires_a_whole_word_not_a_substring` - the other half,
  independent of capitalization: `"Art"` must not ride in on `"Start"`.
- `..._grounds_a_name_the_chapter_states_in_the_plural` - the guard must not
  overcorrect: `"Waste Person"` is grounded by *"Waste persons are..."*.
- `..._still_grounds_a_lowercase_descriptor_entity` - the case-sensitivity
  rule fires only on real names, so a common-noun description a model files
  as a character (`"Old man"` against *"The old man cackled"*) still passes.
- `..._grounds_a_theme_case_insensitively` - `"Courage"` is grounded by
  *"courage"*, because themes/concepts are exempt from the capital rule.

The last three exist because the first version of the fix was too strict and
the real library caught it - they are the regression tests for the
overcorrection, not just for the original bug.

Also covers resumable extraction (`resume_start_index` +
`extract_book(..., restart=)`): a simulated crash (`_FailsAfterNChapters`)
leaves `extraction_progress.json` correctly pointing at the first
un-processed chapter and a resumed call picks up there without
reprocessing earlier chapters; a `KeyboardInterrupt` propagates but still
leaves progress saved (same mechanism, not special-cased in
`extract_book`); a resumed run correctly treats an entity resolved in the
*interrupted* portion as already-known rather than wrongly re-grounding it
(`test_extract_book_resume_reuses_entities_from_the_interrupted_portion` -
this is the specific bug class this feature could have reintroduced if
`known_names` weren't reseeded to include `book_id` itself on resume);
`restart=True` ignores saved progress; a `chapter_count` mismatch (book was
re-ingested) is treated as stale and ignored; and an already-fully-extracted
book is a no-op (provider never called) unless `restart=True`.

Also covers the exact-duplicate-fact filter
(`test_extract_book_drops_exact_duplicate_facts_within_a_chapter`): a
`_FixedResponseProvider` response containing the same `(entity_name,
statement)` pair twice (once case-varied) is deduped to one fact before
being written, with `duplicate_fact_count` reporting how many were
dropped - the code-side guardrail added after a real chapter's real
extraction was found padding toward a raised `maxItems` cap by repeating
the same fact verbatim.

Also covers **which model wrote a book's facts**, added after a resume with a
different model nearly corrupted real data: `extraction_progress.json` records
a `provider` identity (`..._records_which_provider_wrote_the_facts`), resuming
with a different model refuses outright rather than silently mixing two
models' output in one `facts.jsonl` (`..._refuses_instead_of_mixing_facts`),
and the refusal names both models and the way out
(`test_the_refusal_names_both_models_and_the_way_out`) rather than just
failing. Three tests pin down what must *not* be blocked: the same model
resuming normally, `--restart` (which discards the old facts anyway, so a
mismatch is irrelevant), and a book extracted before identities were recorded
at all (`..._before_identities_were_recorded_still_resumes`) - unknown means
unverifiable, never mismatched, so old books stay resumable. A provider that
doesn't implement the optional identity capability is also fine
(`..._that_does_not_identify_itself_can_still_resume`), and an already-complete
book says so rather than reporting a mismatch.

Also covers **entity identity across books**:
`test_extract_book_keeps_unrelated_books_entities_separate` (the pipeline
passes `series_reading_order` as the scope, so two unrelated books never fuse
a same-named character), `test_restart_discards_the_previous_runs_entities`
(the root cause of a real "Michael" anomaly - `--restart` dropped the old
facts but left the entities they created), and
`test_restart_keeps_entities_an_earlier_series_book_still_owns` (the prune
must not reach past this book). `test_extract_persists_entities_after_every
_chapter` pins the durability ordering: facts flush, then `save_entities`,
then the progress write - so a crash can never leave progress claiming a
chapter whose entities were never saved.

Also covers **what makes an alias link survivable and reversible**:

- `test_a_written_fact_records_the_name_the_model_used` — a fact record stores
  `entity_id`, which says which entity owns it but not which name it *arrived*
  as. Without the raw name a wrong merge is permanent and undiagnosable:
  nothing separates the facts that came in as "boy" from those that came in as
  "Conn". Recording `entity_name` is what makes an automatic merge undoable,
  and automatic merging is only acceptable because it is undoable.

- `test_a_declared_alias_group_survives_a_restart` — a confirmed regression,
  not a hypothetical. `--restart` prunes every entity the discarded run
  created, which is correct, but the alias link lived on one of those entities,
  so the prune took the declaration with it and the character silently
  re-split on the next run. That is the worst shape for the bug: the user
  re-runs extraction *because* something looked wrong, and the re-run quietly
  undoes the fix. Sabotage-verified by moving the `declared_aliases.json`
  re-apply back above the prune (the pre-fix order): the first run still yields
  one entity and the restart re-splits it into two, which is exactly the
  reported symptom.

Also covers `known_entity_types` threading
(`test_extract_book_passes_known_entity_types_to_the_provider`): a
`_RecordingProvider` confirms chapter 0 sees an empty type map, and
chapter 1 sees the type `resolve_entity` actually recorded for an entity
introduced in chapter 0 - the mechanism behind the fix for a confirmed
entity-type-drift duplication bug (see `extract/pipeline.py`'s and
`extract/resolve.py`'s context docs).

## Context window sizing and chapter splitting (added 2026-09-23)

`_WindowedProvider` is a stand-in with an Ollama-shaped `extract_num_ctx`;
`_PerCallProvider` records the text of every call, so a test can see how many
pieces a chapter became.

- `test_context_window_is_sized_down_for_a_book_of_short_chapters` /
  `test_context_window_grows_with_the_books_longest_chapter` — sized from the
  **longest** chapter, not the median. One oversized chapter still has to fit,
  and a window that truncates it loses facts silently.
- `test_context_window_never_exceeds_the_ceiling` — this may only narrow what
  the user configured, never widen it.
- `test_context_window_respects_a_user_who_already_chose_a_small_one` — a
  deliberately small `$OLLAMA_EXTRACT_NUM_CTX` is not raised by a book that
  would like more room. Narrow-only is also what makes the function safe to
  call twice (cli preview, then pipeline).
- `test_extract_book_reports_no_window_for_a_provider_without_one` — `None`
  means "nothing to report", not a default, for Anthropic and the fakes.
- `test_every_fact_from_a_split_chapter_keeps_the_chapters_own_index` — **the
  property the whole splitting design rests on.** Splitting is for the model
  only; `chapter_index` still addresses the chapter, which is what leaves
  spoiler filtering, citations and `chat --chapter N` untouched. If this ever
  fails, facts have moved into the wrong chapter and the spoiler guarantee is
  gone.
- `test_a_new_entity_is_grounded_against_the_whole_chapter_not_one_piece` — a
  character named only in the first piece must not be rejected as
  hallucinated when the fact about them comes back from a later piece. The
  easy wrong implementation (ground against the piece) passes every other test
  here and fails this one.

### Splitting is opt-in (added 2026-09-23)

- `test_an_oversized_chapter_is_not_split_by_default` — the default path makes
  exactly one provider call for a 6,000-word chapter. Pinned because
  `consolidate.SPLIT_OVERSIZED_CHAPTERS` is off on measured evidence (six
  chapters, no surviving decision rule) and flipping it silently changes 48 of
  The Eye of the World's 108 chapters.
- `test_an_oversized_chapter_is_extracted_in_pieces_when_enabled` and
  `test_a_new_entity_is_grounded_against_the_whole_chapter_not_one_piece` both
  `monkeypatch.setattr(consolidate, "SPLIT_OVERSIZED_CHAPTERS", True)`, so the
  split path stays genuinely exercised while the default stays off. Patching
  the module attribute rather than the imported name is what makes it reach
  `split_for_extraction`, which reads it at call time.
