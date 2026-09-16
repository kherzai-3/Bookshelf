---
source: tests/test_alias_linking.py
last_synced: 2026-09-16T20:32:36Z
source_hash: 5bc375618394b4e30b59698fc82592261135b35a
---

## Purpose
Pins the guarantees that make automatic narrator-alias linking safe. The
feature spans three modules that have to agree — `ingest.vocatives` decides
what to link, `extract.resolve` applies it, `query` deliberately declines to —
and the central property is a *relationship between two of them*, so it has no
natural home in any single module's test file. This file is that home.

The first test is the load-bearing one; everything else here supports it.

## Public Interface
Pytest test functions only. No exported helpers.

## Key Decisions

**Why the epithet test asserts across two modules at once.** `aliases` and
`epithets` are separate fields solely because their consumers match
differently: `resolve_entity` compares exact `match_key`s, `select_relevant_facts`
substring-matches against a question. Asserting either half alone proves
nothing — "epithets resolve" is satisfiable by folding them into `aliases`, and
"epithets don't answer questions" is satisfiable by dropping them entirely
(the design that was rejected, at a cost of ~750 references on one real book).
Only the pair pins the actual shape.

**Sabotage-verified, per this project's standard.** Adding
`*entity.get("epithets", [])` to `select_relevant_facts`'s `candidate_names`
— a one-word edit that reads like a bug fix — fails
`test_an_epithet_resolves_an_extracted_fact_but_never_answers_a_question` and
**nothing else in the 414-test suite**. That measurement is the reason this
file exists: before it, the property was held by a source comment alone.

**The fixture carries a second character on purpose.** `select_relevant_facts`
returns *every* fact when a question names no entity at all. So a test asserting
"this question did not retrieve Conn" needs the question to retrieve somebody
else, or it passes for the wrong reason — the fallback would return Conn's facts
along with everything else and the assertion would be measuring nothing. The
question is shaped as "the boy that Benet trained", which is also the realistic
hazard: a question about some *other* boy.

**`auto_link_plan` cases are drawn from measured failures, not invented ones.**
`Magister` is the case that killed capitalisation-alone: 5/5 capitalised in the
reported book, and actually Keeston addressing *Nevery* while the narrator
stands by. An earlier version of this plan excluded epithets on the strength of
a query that turned out to appear zero times in the book it was attributed to,
so every case here is one that was counted.

## Dependencies
- Internal: `extract.resolve` (`resolve_entity`, `save_entities`,
  `seed_alias_group`), `ingest.vocatives` (`AliasCandidate`, `NarratorAliases`,
  `auto_link_plan`), `query` (`Fact`, `select_relevant_facts`)
- External: `pytest`

## Data Contracts
Builds `entities.json` shapes inline: an entity with both `aliases` and
`epithets` lists. `_facts` builds `query.Fact` objects directly rather than
running extraction — the tests are about matching, not about the pipeline.

## Open Questions / TODOs
- The real-data retrieval check (Arald/Tyler/Fergus before-and-after, and the
  narrator not surfacing for a "boy" question) still runs by hand against a
  copy of `data/library`. Nothing in the suite covers a library at that scale.
- `unlink_names` separates names but not facts; the splitter that would use the
  recorded `entity_name` to re-decide fact ownership is not built, so nothing
  here tests it.
