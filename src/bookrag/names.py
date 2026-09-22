"""Surface forms of a name in a book's own prose, and what they are evidence of.

Two consumers, deliberately sharing one core so they cannot drift apart about
what a name looks like:

- `library.detect_name_variants` runs the residue rule over *entity names*,
  after extraction, and proposes merges through `bookrag doctor`.
- `cli` runs `person_link_groups` over *chapter text*, at ingest, and links
  without asking - the only path a reader actually walks.

The two differ in one place only, and for a good reason: after extraction
there are entity types, so `library` can simply require both sides to be
characters. At ingest there are none, so personhood has to be read out of the
prose. See `reads_as_a_person`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

# Thresholds measured over the whole eight-book corpus, not tuned on one book -
# see library._residue_variant_pairs for the scoring.
MIN_DECORATED = 10  # the decorated form is real, not a hapax
MIN_BARE = 100  # the bare name is established in its own right
MIN_LOWERCASE = 25  # at which point the book treats the word as ordinary

# How far the bare name has to outnumber the decorated form. **Two values, and
# the difference is what being wrong costs on each path, not a disagreement
# about the evidence.** Both were hand-scored over the same 8 books:
#
#   3x  250 links, 240 correct, 96.0%   doctor: a bad proposal costs one "n"
#   5x  237 links, 230 correct, 97.0%   ingest: a bad merge is silent, and
#                                       undoing it means --unlink plus a
#                                       5h27m re-extraction
#
# Loosening to 3x buys 10 correct links (`Captain Kerrn` -> `Kerrn`, `Big Fat
# Adam` -> `Adam`, `Lord Wolf King` -> `Wolf King`) and 3 wrong ones, all of
# one shape already known here: a thing named after a person, or a rank many
# people share (`Great Love Immortal Venerable` -> `Immortal Venerable`,
# `Plunder Shadow Earth Trench` -> `Earth Trench`, `Little Hu Immortal` ->
# `Hu Immortal`). `reads_as_a_person` catches two of those three, so on the
# auto-linking path 3x would cost 98.4% against 5x's 99.2%.
PROPOSE_RATIO = 3.0
AUTOLINK_RATIO = 5.0

# Maximal runs of capitalised words, which is what makes the comparison mean
# anything: "Fang Yuan" counts only its bare mentions, and "Lord Fang Yuan" is
# counted separately rather than folded into it.
CAPITALISED_RUN = re.compile(r"[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,4}")
_WORD = re.compile(r"[A-Za-z]+")

# A name containing one of these past its first token is a compound of two
# people, not a longer form of one - "Tug And Blaze".
CONJUNCTIONS = frozenset({"and", "&", "or", "plus", "with"})


@dataclass
class NameFrequencies:
    """How one book uses each capitalised run and each lowercase word."""

    runs: Counter = field(default_factory=Counter)  # maximal run -> occurrences
    lowercase: Counter = field(default_factory=Counter)  # lowercase word -> occurrences
    inside: Counter = field(default_factory=Counter)  # token -> occurrences inside a longer run


def name_frequencies(texts: Iterable[str]) -> NameFrequencies:
    freq = NameFrequencies()
    for text in texts:
        for word in _WORD.findall(text):
            if word.islower():
                freq.lowercase[word] += 1
        for match in CAPITALISED_RUN.finditer(text):
            freq.runs[" ".join(match.group(0).split())] += 1

    for run, count in freq.runs.items():
        tokens = run.split()
        if len(tokens) > 1:
            for token in set(tokens):
                freq.inside[token] += count
    return freq


def residue_stands_alone(residue: str, freq: NameFrequencies) -> bool:
    """Whether what is left after stripping a prefix is a name in its own
    right. Two guards, each catching a failure the other misses - measured,
    not assumed. On Reverend Insanity guard A alone proposes 355 links and
    strips surnames and category nouns ("Moonlight Gu" -> "Gu", "Liu Wen Wu"
    -> "Wu"); guard B alone proposes 221 and strips capitalised pronouns
    ("Chi Qu You" -> "You", "Qin Bai He" -> "He"). Together, 203 and 2 wrong."""
    tokens = residue.split()
    if len(tokens) > 1:
        # A multi-token residue is already a name shape; neither guard applies,
        # and "Gu Yue Fang Yuan" -> "Fang Yuan" is the case that needs this.
        return True
    token = tokens[0]
    # (A) The book itself treats the word as ordinary vocabulary. Deliberately
    # a per-book count and nothing wider: an earlier version also required the
    # word to appear in 6 of the 8 books in *this* library, which measured 3
    # links better but cannot ship - a three-book library can never satisfy it,
    # and the rule would silently degrade to guard B alone. Dropping it loses
    # "Four Flavours Liquor" -> "Liquor", which was a scored error anyway.
    if freq.lowercase[token.lower()] >= MIN_LOWERCASE:
        return False
    # (B) The bare form outnumbers the token's use inside longer names. A
    # family name or a category noun fails this: it almost only ever appears
    # attached to something else.
    return freq.runs[residue] > freq.inside[residue]


def residue_of(name: str, freq: NameFrequencies, ratio: float = PROPOSE_RATIO) -> str | None:
    """The better-attested name left behind when leading tokens are stripped,
    or None to keep the name whole. **Nothing here classifies the prefix**,
    and that is the point - see `library._residue_variant_pairs`.

    `ratio` defaults to the propose-only setting; the auto-linking path passes
    the stricter `AUTOLINK_RATIO`."""
    tokens = [token for token in name.split() if token]
    if len(tokens) < 2:
        return None
    # "Tug and Blaze" is two horses the extractor filed as one entity.
    # Stripping to "Blaze" would pick one of them as the survivor. Only a
    # *non-leading* conjunction makes that shape: a leading one is a
    # sentence-initial word ("And Fang Yuan"), which is the case this rule
    # deliberately links straight back to the bare name - vetoing those too
    # costs 4 correct links across the corpus and protects nothing.
    if any(token.strip(".,").lower() in CONJUNCTIONS for token in tokens[1:]):
        return None
    decorated = freq.runs.get(" ".join(tokens), 0)
    if decorated < MIN_DECORATED:
        return None

    best, best_count = None, 0
    for index in range(1, len(tokens)):
        residue = " ".join(tokens[index:])
        count = freq.runs.get(residue, 0)
        if count < MIN_BARE or count < decorated * ratio:
            continue
        if not residue_stands_alone(residue, freq):
            continue
        if count > best_count:
            best, best_count = residue, count
    return best


# ---------------------------------------------------------------------------
# Reading personhood out of the prose, for the ingest path only.

_DETERMINER_WORDS = (
    "the a an this that these those its his her their my your our "
    "each every another some any no"
).split()
# Both capitalisations spelled out rather than re.IGNORECASE, which would also
# lowercase the name and defeat the proper-noun test itself.
_DETERMINERS = "(?:" + "|".join(
    [w.capitalize() for w in _DETERMINER_WORDS] + _DETERMINER_WORDS
) + ")"

# Deliberately excludes "added", "continued", "spoke", "called", "cried" and
# "thought": each fires on things as readily as on people, and an earlier
# version carrying them scored "Blue Elixir" as a speaker.
_SPEECH_VERBS = (
    "said|says|asked|asks|replied|replies|answered|answers|shouted|shouts"
    "|muttered|whispered|nodded|nods|smiled|smiles|laughed|laughs|sighed"
    "|grinned|frowned|exclaimed|murmured|chuckled|snorted|sneered|shrugged"
    "|growled|hissed|stammered|retorted|snapped"
)

MAX_DETERMINER_SHARE = 0.10
MIN_SPEECH_SIGHTINGS = 3


def reads_as_a_person(name: str, text: str, freq: NameFrequencies) -> bool:
    """Whether the book uses this name the way it uses a person's name.

    **Needed only because `seed_alias_group` writes `type="character"`.**
    `resolve_entity` is type-scoped, so seeding a place or a category as a
    character cannot help: extraction mints its own setting or concept entity,
    the fragmentation is not fixed, and the seeded record is left an orphan for
    `doctor` to report. The `library` path has real entity types and simply
    requires both sides to be characters; this is the type-blind stand-in.

    Two signals, both required, and each measured against the alternative of
    going without:

    - **A proper noun takes no determiner.** Nobody writes "the Fang Yuan",
      and everybody writes "the Elixir". Measured over the corpus this
      separates the two classes cleanly - every genuine person among the
      proposals sits under 6% ("Qi Sea Ancestor" is the highest at 5.2%),
      while categories start around 15% ("Gu Immortals") and run to 94%
      ("Meta"). The threshold is 10%, roughly twice the highest real person
      rather than just above them, because a threshold sitting on top of a
      real observation is how 02b nearly lost its only evidenced book.
    - **A person is the subject of a speech or gesture verb.** "Fang Yuan
      said", "said Nevery", "Ahab nodded". This is what rejects the plural
      categories the determiner test lets through, and what the determiner
      test rejects in turn is a category whose members speak.

    **Neither alone is enough, and that was measured rather than assumed.**
    The speech test alone keeps every one of the 7 known errors, because
    "Augustus" is a real person that "Mount Augustus" is named after. The
    determiner test alone admits "Gu Immortals" and "Gu Masters", which are
    categories, as characters."""
    escaped = re.escape(name)
    sightings = freq.runs.get(name, 0)
    if not sightings:
        return False
    determined = len(re.findall(rf"\b{_DETERMINERS}\s+{escaped}\b", text))
    if determined / sightings >= MAX_DETERMINER_SHARE:
        return False
    speaking = len(re.findall(rf"\b{escaped}\s+(?:{_SPEECH_VERBS})\b", text)) + len(
        re.findall(rf"\b(?:{_SPEECH_VERBS})\s+{escaped}\b", text)
    )
    return speaking >= MIN_SPEECH_SIGHTINGS


@dataclass
class NameLinkGroup:
    """One person, and the decorated forms of their name in this book."""

    name: str  # the bare, better-attested form - the canonical one
    decorated: list[str]  # "Lord Fang Yuan", "Gu Yue Fang Yuan", ...
    sightings: int  # bare-form occurrences, for reporting


def person_link_groups(texts: Iterable[str], ratio: float = AUTOLINK_RATIO) -> list[NameLinkGroup]:
    """Every person in this book whose name also appears decorated, read from
    the text alone - no entity registry, so this works at ingest, before any
    extraction has happened.

    **Slow on a long book, and deliberately not optimised**: `reads_as_a_person`
    scans the whole text twice per candidate, which is about 110 seconds on the
    2,360-chapter book in the corpus and under two on everything else. Ingest is
    a once-per-book cost paid to save hours of extraction producing a fragmented
    catalog, so the caller announces the wait rather than the code avoiding it -
    see `cli.auto_link_title_variants`, and `extract_start_notes` for the same
    decision made about model loading.

    Ordered by how often the bare name occurs, so the most consequential
    grouping is the one a reader sees first."""
    text = "\n".join(texts)
    freq = name_frequencies([text])

    links: dict[str, str] = {}
    for candidate in freq.runs:
        if " " not in candidate:
            continue
        residue = residue_of(candidate, freq, ratio)
        if residue is not None:
            links[candidate] = residue

    grouped: dict[str, list[str]] = {}
    for decorated, residue in links.items():
        grouped.setdefault(residue, []).append(decorated)

    groups = [
        NameLinkGroup(name=residue, decorated=sorted(forms), sightings=freq.runs[residue])
        for residue, forms in grouped.items()
        if reads_as_a_person(residue, text, freq)
    ]
    return sorted(groups, key=lambda group: -group.sightings)
