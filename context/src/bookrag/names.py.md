---
source: src/bookrag/names.py
last_synced: 2026-09-22T21:20:00Z
source_hash: 0ba85bdc2b28af8de94f4081737d3856c5e2e8f5
---

## Purpose
The residue rule's shared core: how a book writes its characters' names, and
what that is evidence of. Two consumers deliberately share one definition so
they cannot drift apart about what a name looks like —
`library.detect_name_variants` (entity names, after extraction, proposed
through `doctor`) and `cli.auto_link_title_variants` (chapter text, at ingest,
applied without asking).

Build-order item **02c(i)+(ii)+(vi)**. It exists because a character
fragmented across a title, a clan prefix and a bare name — *Reverend
Insanity*'s protagonist is `Fang Yuan`, `Gu Yue Fang Yuan`, `Lord`/`Elder Fang
Yuan` and about thirty surface forms, of which the pre-existing rules reached
**one**, and only because `lord` happens to sit in `_TITLES`.

## Public Interface
- `NameFrequencies` (dataclass) — `runs` (maximal capitalised run →
  occurrences), `lowercase` (lowercase word → occurrences), `inside` (token →
  occurrences inside a *longer* run).
- `name_frequencies(texts) -> NameFrequencies` — one pass over a book's prose.
- `residue_stands_alone(residue, freq) -> bool` — guards A and B.
- `residue_of(name, freq, ratio=PROPOSE_RATIO) -> str | None` — the
  better-attested name left behind, or None to keep the name whole.
- `people_among` / `reads_as_a_person(name, text, freq) -> bool` — the
  ingest-only personhood test.
- `NameLinkGroup` (dataclass) — `name` (the bare, canonical form), `decorated`
  (its decorated forms), `sightings`.
- `person_link_groups(texts, ratio=AUTOLINK_RATIO) -> list[NameLinkGroup]` —
  what ingest links, read from text alone with no entity registry.

## Key Decisions

**Do not classify the prefix; test the residue.** Three classifiers were built
against the full text and all three failed — the best read invented name-parts
(`Northern`, `Yellow`, `Blood`, `Star`) as ranks and put the real ranks
`Elder` and `Senior` in the reject bucket, because a book's invented
vocabulary is English-shaped. So a leading token is stripped only when what
remains is a better-attested name in the same book:

```
link "P R" -> R iff
  freq(R) >= 100  and  freq(R) >= ratio x freq(P R)
  freq(P R) >= 10                  # the decorated form is real, not a hapax
  R stands on its own              # guards A and B, both required
```

Frequencies are **maximal runs of capitalised words**, so `Fang Yuan` counts
only its bare sightings and `Lord Fang Yuan` is counted separately rather than
folded into it.

**Guards A and B are both required, measured.** A residue of 2+ tokens is
already name-shaped and needs neither. For a single token: (A) the book must
not use the word lowercase 25+ times, (B) the bare form must outnumber the
token's use inside longer names. On *Reverend Insanity* A alone gives 355
links and strips surnames and category nouns (`Moonlight Gu` → `Gu`); B alone
gives 221 and strips capitalised pronouns (`Chi Qu You` → `You`). Together:
203 links, 2 wrong.

**Two ratios, because being wrong costs differently on each path.** Both
hand-scored over the same 8 books:

| | links | correct | | |
|---|---|---|---|---|
| `PROPOSE_RATIO` 3.0 | 250 | 240 | 96.0% | doctor: a bad proposal costs one keystroke |
| `AUTOLINK_RATIO` 5.0 | 237 | 230 | 97.0% | ingest: a bad merge is silent; undo is `--unlink` + a 5h27m re-extraction |

Loosening to 3x buys 10 correct links (`Captain Kerrn` → `Kerrn`, `Big Fat
Adam` → `Adam`, `Lord Wolf King` → `Wolf King`) and 3 wrong ones, all of a
shape already known here — a thing named after a person, or a rank many people
share: `Great Love Immortal Venerable` → `Immortal Venerable`, `Plunder Shadow
Earth Trench` → `Earth Trench`, `Little Hu Immortal` → `Hu Immortal`.
`reads_as_a_person` catches two of those three, so on the auto-linking path 3x
would score 98.4% against 5x's 99.2%.

**The rejected guard, recorded so it is not revived.** Requiring the prefix to
be *productive* — to decorate several different identities — removes 5 of the
9 original errors and costs 58 links, taking precision from 96.3% to 97.8% by
losing roughly 53 correct links.

### `reads_as_a_person` — the ingest-only guard

Needed only because `resolve.seed_alias_group` writes `type="character"` and
`resolve_entity` is type-scoped: seeding a place or a category as a character
cannot help. Extraction mints its own setting/concept entity, the
fragmentation is not fixed, and the seeded record is left an orphan for
`doctor` to report. `library` has real entity types and simply requires both
sides to be characters; this is the type-blind stand-in.

Two signals, both required, **and neither is sufficient — that was measured,
not assumed**:

- **A proper noun takes no determiner.** Nobody writes "the Fang Yuan";
  everybody writes "the Elixir". Every genuine person among the proposals sits
  under 6% determiner share (`Qi Sea Ancestor` highest at 5.2%); categories
  start around 15% (`Gu Immortals`) and run to 94% (`Meta`). The threshold is
  **10%**, roughly twice the highest real person rather than just above them —
  a threshold sitting on top of a real observation is how 02b nearly lost its
  only evidenced book.
- **A person is the subject of a speech or gesture verb.** "Fang Yuan said",
  "said Nevery", "Ahab nodded".

The determiner test alone admits `Gu Immortals` and `Gu Masters`, categories
whose members talk constantly. The speech test alone keeps **every one** of
the 7 known errors, because `Augustus` is a real person that `Mount Augustus`
is named after — an earlier version of it also carried `added`, `continued`
and `spoke` in the verb list, which fire on objects ("Blue Elixir added
to..."), and scored an elixir as a speaker.

**Result on the corpus: 124 links in 50 groups, 1 wrong** — `Mount Augustus` →
`Augustus`, which no text signal can catch and which entity types do.

**Deliberately not optimised.** `reads_as_a_person` scans the whole text twice
per candidate, which is ~110 seconds on the 2,360-chapter book and under two
on everything else. Ingest is a once-per-book cost paid to avoid hours of
extraction producing a fragmented catalog, so the caller announces the wait
rather than the code avoiding it. A batched single-pass version is
straightforward if that ever stops being true.

## Dependencies
- Internal: none — deliberately. `library` and `cli` both import *this*;
  nothing here imports either, so there is no cycle and the rule can be
  measured standalone.
- External: stdlib `re`, `collections.Counter`.

## Data Contracts
`NameLinkGroup` is what `cli.auto_link_title_variants` hands to
`library.link_names` as `[group.name, *group.decorated]` — the bare name first,
so it becomes the canonical name and the decorated forms become aliases.

## Open Questions / TODOs
- `Mount Augustus` → `Augustus` is the one error the ingest guard cannot
  reach. A geographic-classifier wordlist (`Mount`, `Lake`, `Fort`) would
  catch it and reintroduces exactly the wordlist this rule exists to avoid.
- The corpus's two nonfiction books propose nothing, so the personhood guard
  has never been exercised against a nonfiction false positive in anger.
- `Heavenly Court` and `Lang Ya` clear the guard on *Reverend Insanity* and
  are an organisation and a place. They are the accepted residue of a
  text-only test; entity types would reject both.
