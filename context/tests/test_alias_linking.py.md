---
source: tests/test_alias_linking.py
last_synced: 2026-09-17T18:23:32Z
source_hash: 036685ea944c25f241d267fb887176e9b6714de5
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

**The epithet-attachment tests encode a measurement, not a preference.** Three
tests pin `_epithets_for`:
- `..._surrenders_an_epithet_to_a_rival_narrator` is the bug. Grouping only
  refuses a book with two qualifying name *groups*; give the second narrator one
  spelling and she forms a group of one, so the first narrator's pair links as
  normal and her `girl` rides along onto him.
- `..._an_epithet_with_no_rival_is_kept_even_sharing_no_chapter_with_a_name` is
  the counterweight, and the reason the rule is comparative. The obvious
  absolute version — require overlap with the linked names' chapters — drops
  `shadow` and `cousin` on the real book, both genuinely addressed to the
  narrator. Without this test the bug test above is satisfied by the rule that
  breaks the one book the feature works on.
- `..._one_shared_chapter_does_not_hand_an_epithet_to_a_rival` pins
  `_MIN_RIVAL_CHAPTERS = 2`. `cousin` and `Magister` coincide in exactly one
  chapter of the real book, and at a threshold of 1 that took a real epithet
  off the narrator.

`_candidate`/`_a_name` take an optional `chapters` set; tests not about chapter
evidence leave it empty, which reads as "no rival competes" and leaves their
behaviour unchanged.

`_candidate` also defaults `times_in_trailing_position` to `times_addressed`,
i.e. a candidate seen only in trailing position — which is what the corpus
overwhelmingly contains (every real candidate across all eight books except
`Conn` has the two counts equal). **A derived default in a hand-built fixture is
exactly the shape that once let this suite agree with itself and not with
production**, so the gap between the two counts is covered end to end, against
the real detector, in `test_vocatives.py`; this file only exercises the ratio.
`test_a_capitalised_vocative_reads_as_a_name_and_a_lowercase_one_does_not`
carries the one explicit case (Conn, 22 of 26) so the distinction is visible
here too.

**The two-narrator case is the one that bites hardest.**
`test_auto_link_plan_refuses_a_book_with_two_narrators` pins that two name
pairs stay two people. The rule checked both signals pairwise and then treated
every survivor as one set, so `Conn`/`Connwaer` plus `Row`/`Rowena` came back
as a single four-name character — and `auto_link_plan` feeds `link_names` at
ingest without asking, so that lands in `entities.json` before extraction runs.
`..._still_links_one_narrator_beside_an_unrelated_name` is its required
counterweight: the narrowing must not cost the real Magic Thief shape, where a
capitalised bystander (`Magister`) sits beside the one true pair. Without it,
the refusal test would be satisfied by a rule that never links anything.

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
