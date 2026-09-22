---
source: tests/test_names.py
last_synced: 2026-09-22T21:20:00Z
source_hash: a5b005bdeb480c4824d8d9ac58585a44259a5885
---

## Purpose
Covers `bookrag.names` — the residue rule's shared core, and the personhood
test that lets it run at ingest where no entity types exist yet.

Deliberately split from `tests/test_library.py`, which covers the *same rule*
applied to entity names through `doctor`. This file covers it applied to
**text**, which is the auto-linking path: `person_link_groups` is what
`cli.auto_link_title_variants` calls, and `reads_as_a_person` is the guard
standing in for `doctor`'s characters-only restriction.

## Key Decisions

- **`_prose` builds fixtures by repeating a sentence per name**, because the
  rule's only evidence is frequency in the book's own text. Every word
  surrounding a name is lowercase on purpose: a capitalised one would join the
  maximal run and change the very frequency the fixture exists to set.
- **`_speech` is a separate helper** rather than folded into `_prose`, because
  the two signals it feeds are independent — a fixture that is determiner-free
  but silent is exactly the "place, not person" case, and one test needs it
  that way.
- **The two ratios are pinned by one parametrised assertion**
  (`test_the_two_paths_disagree_only_where_being_wrong_costs_differently`)
  using the real case that motivated the split: *The Magic Thief* writes
  "Kerrn" 284 times and "Captain Kerrn" 81, a ratio of 3.5, so `doctor` offers
  the link and ingest declines it. Setting `AUTOLINK_RATIO` to `PROPOSE_RATIO`
  fails exactly this test.

## Tests, and what each is load-bearing for

Linking:
- `..._strips_a_title_no_wordlist_contains` — "Magister" is a rank the book
  invented, so no closed list can hold it.
- `..._keeps_a_name_that_stands_on_its_own` — the bare name is not itself
  stripped.
- `..._gathers_every_decorated_form_of_one_name` — four forms arrive as one
  group with the bare name canonical, which is the shape `link_names` wants,
  and is 02c(ii) dissolving.
- `..._keeps_two_people_of_one_clan_apart` — two characters sharing a clan
  prefix stay two groups.

The personhood guard, one test per signal, each verified by deleting that
signal alone:
- `test_a_person_is_a_proper_noun_the_book_lets_speak` — the positive case.
- `test_a_category_is_rejected_however_often_its_members_speak` — the
  determiner half. "Gu Immortals" is a category whose members talk constantly,
  so the speech signal alone accepts it; measured, that is exactly how "Gu
  Immortals" (14.5% determiner share) and "Gu Masters" (17.9%) got through.
- `test_a_place_is_rejected_however_proper_its_name_looks` — the speech half.
  A place name can be as determiner-free as a person's, so the only thing
  separating "Earth Trench" from a character is that nobody hears it speak.
- `test_person_link_groups_says_nothing_about_a_book_of_categories` — the
  nonfiction case, and the reason auto-linking is safe to run on every book.
  A qualified variety of a category ("Blue Elixir") is the residue rule's one
  known failure shape, and the personhood guard is what stops it being
  *applied*.

## Open Questions / TODOs
- Nothing here exercises `Mount Augustus` → `Augustus`, the one error the
  ingest guard provably cannot catch. It is recorded in `names.py`'s context
  doc rather than pinned as a test, because a test asserting the wrong answer
  would have to be rewritten by whoever fixes it and reads as intent.
