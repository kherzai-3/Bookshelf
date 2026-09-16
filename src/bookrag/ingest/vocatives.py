"""Who the other characters call the narrator, read straight out of the prose.

This runs at ingest, on chapter text alone - no model, no extraction, no
entity registry. That is the whole point of it. The catalog fragments a
character across every name the book uses for them ("Conn", "Connwaer",
"boy", "lad"), and the repair for that previously lived in
`bookrag doctor --merge-name-variants`, which only ever runs when somebody
knows to type it. Running here instead puts the answer on the path people
actually walk, and early enough that extraction could be told about it rather
than having its output patched afterwards.

**The signal is who is speaking, not what is said.** A vocative sits in
quoted dialogue, and in a first-person book an utterance spoken by anyone
other than the narrator is, in a two-hander, addressed *to* the narrator. So
splitting vocatives by speaker splits "what people call me" from "what I call
people", and nothing else is needed. Measured on the reported book that
separation is total:

    others address him : boy 34   conn 12   lad 4   connwaer 3
    he addresses others: nevery 12   pip 7   kerrn 6

Approaches tried first and rejected, each on real data:
- **A naming construction in the text** ("Connwaer, called Conn"). The book
  never says it. Zero sentences in 230,518 words contain both names; the link
  is made exactly once, as bare apposition in dialogue. Meanwhile the
  construction itself fires 59 times in one book and 128 in another, almost
  always about a class ("beasts known as the Kalkara"), so it is loose as well
  as absent.
- **A first-person pronoun in the surrounding narration.** In a first-person
  book every narration window says "me", so this ranked the narrator's own
  name for his master as highly as his own.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from bookrag.extract.resolve import looks_like_a_name_variant
from bookrag.ingest.chapter import Chapter

# Publishers differ, and a hardcoded pair fails *silently* - it returns zero
# spans, which reads exactly like "this book has no dialogue". Really observed:
# The Magic Thief uses curly doubles, Ranger's Apprentice curly singles.
_QUOTE_PAIRS = (("“", "”"), ("‘", "’"), ('"', '"'))

# Only the closing single curly quote is ambiguous: it is also the apostrophe
# in "don't". A closing quote is never immediately followed by a letter.
_AMBIGUOUS_CLOSER = "’"

_MAX_UTTERANCE = 400

# First-person pronouns per 100 words of *narration* (dialogue removed).
# Measured per chapter across three real novels: The Magic Thief runs a median
# of 7.11 and a lower quartile of 6.03; Ranger's Apprentice peaks at 3.45 and
# has a median of 0.48. 4.0 sits in that gap. Judged per chapter rather than
# per book on purpose - see `detect_narrator_aliases`.
_FIRST_PERSON_PER_100_WORDS = 4.0

# Below this a chapter is front matter or a fragment, and its ratio is noise.
_MIN_NARRATION_WORDS = 50

# A single sighting is not evidence. The trailing-vocative shape also matches
# an utterance that merely ends in ", <word>." - real one-offs harvested from
# the reported book include "hurry", "quiet", "stoichiometry". Every genuine
# alias in that book clears 2, and the long tail below it is entirely noise.
_MIN_TIMES_ADDRESSED = 2

# A closed list, deliberately. Generalising to "any word ending -ed or -s"
# was tried and degraded attribution immediately: it matched ordinary verbs in
# the sentence after an utterance and filed the narrator's own lines under
# somebody else.
_SPEECH_VERBS = (
    r"(?:said|says|asked|asks|replied|answered|answers|muttered|snapped|growled|"
    r"whispered|shouted|called|added|cried|demanded|observed|remarked|agreed|"
    r"admitted|hissed|murmured|repeated|began|continued|put in|went on)"
)

_SPEAKER = r"(I|[Hh]e|[Ss]he|[A-Z][a-z]+)"

# A candidate must be addressed *more* often than it is caught speaking.
# The narrator of a first-person book is never a speech-tag subject - they are
# "I" - so a name that speaks is somebody else's. Measured on the reported
# book this separates cleanly: every confirmed error sits at or below 1.0
# (trammel 0.12, argent 0.16, you 0.29, captain 0.75) and every confirmed
# alias above it (connwaer 24.0, boy 5.6, conn 4.3), with one correct name
# lost at the boundary (gutterboy, exactly 1.0). Losing a real epithet costs
# a retrieval near-miss; keeping a real character costs a merged identity.
_MIN_ADDRESSED_TO_SPOKEN = 1.0

# Words that open an utterance followed by a comma and are not names.
# Only needed for the leading vocative position; the trailing one ("..., boy.")
# is unambiguous.
_NOT_A_VOCATIVE = frozenset(
    """yes no well hello hullo hi now here there then too what oh ah ahh ahhh eh
    please right righty righty-o listen look see really but and so why wait aye
    good better best thank thanks sure maybe course indeed nonsense of all just
    still even though because after before first next finally anyway besides
    actually certainly exactly true false nope yeah yep say sorry excuse""".split()
)


# Terms of address that belong to whoever is being spoken to, and so say
# nothing about who that is. Distinct from "boy"/"lad"/"thief", which describe
# a particular person in context - these are pure politeness and attach to
# anyone. Each one survives the speaker filters on real data by being addressed
# to a third party while the narrator stands by.
_ANYONES_TERM_OF_ADDRESS = frozenset(
    "sir dear madam ma'am maam boss mate lord lady master mistress friend".split()
)

# Share of trailing-position sightings that must be capitalised before a
# vocative reads as a *name* rather than an epithet. Trailing position only:
# a leading vocative is sentence-initial and capitalised whatever it is.
# Measured on a real book the split is near-total - Connwaer 24/24 and Conn
# 22/22, against boy 1/106, lad 0/14, sir 0/12, thief 0/3 - so the exact
# threshold barely matters; 0.8 leaves room for a stray sentence-initial catch.
_NAME_CAPITALISATION_SHARE = 0.8


@dataclass
class AliasCandidate:
    """One name the book uses for its narrator, with the evidence for it."""

    name: str  # the most common surface form, e.g. "Connwaer" or "boy"
    times_addressed: int
    times_capitalised: int  # in trailing position, where capitalisation means something

    @property
    def reads_as_a_name(self) -> bool:
        """A proper noun, so safe to expose to question matching; otherwise an
        epithet, which is only safe at extraction time (see this module's
        context doc for why the two are not interchangeable)."""
        return self.times_capitalised >= self.times_addressed * _NAME_CAPITALISATION_SHARE

    @property
    def is_anyones_term_of_address(self) -> bool:
        return self.name.lower() in _ANYONES_TERM_OF_ADDRESS


@dataclass
class NarratorAliases:
    """What the book calls its narrator, and enough context to judge it."""

    aliases: list[AliasCandidate] = field(default_factory=list)
    # What the narrator calls *other* people. Not an alias list - kept because
    # it is the control that shows the split worked, and a reviewer comparing
    # the two columns can see at a glance whether attribution went wrong.
    addressed_by_narrator: list[tuple[str, int]] = field(default_factory=list)
    # Vocatives that landed in both columns and lost. A misread attribution tag
    # puts a stray count in the wrong column, so the rule is comparative rather
    # than absolute: a name the narrator uses for other people more often than
    # other people use it for the narrator is somebody else's name.
    ambiguous: list[tuple[str, int, int]] = field(default_factory=list)  # (name, to, by)
    # Candidates rejected because they are themselves speakers - other
    # characters the narrator merely overheard being addressed.
    # (name, times addressed, times speaking)
    speakers: list[tuple[str, int, int]] = field(default_factory=list)
    first_person_chapters: list[int] = field(default_factory=list)
    chapters_considered: int = 0
    quote_style: str | None = None  # a human-readable name, for diagnosing a silent zero

    @property
    def is_first_person(self) -> bool:
        return bool(self.first_person_chapters)


def _best_quote_pair(text: str) -> tuple[tuple[str, str] | None, list[re.Match]]:
    """Whichever pair actually delimits dialogue in this book. Picked by which
    yields the most spans rather than assumed, because guessing wrong yields
    silence rather than an error."""
    best_pair, best_spans = None, []
    for opener, closer in _QUOTE_PAIRS:
        inner = r"[^" + re.escape(opener) + re.escape(closer) + r"]{1," + str(_MAX_UTTERANCE) + r"}"
        guard = r"(?![A-Za-z])" if closer == _AMBIGUOUS_CLOSER else ""
        spans = list(re.finditer(re.escape(opener) + "(" + inner + ")" + re.escape(closer) + guard, text))
        if len(spans) > len(best_spans):
            best_pair, best_spans = (opener, closer), spans
    return best_pair, best_spans


def _quote_style_name(pair: tuple[str, str] | None) -> str | None:
    return {
        ("“", "”"): "curly double",
        ("‘", "’"): "curly single",
        ('"', '"'): "straight double",
    }.get(pair) if pair else None


def _strip_dialogue(text: str) -> str:
    pair, spans = _best_quote_pair(text)
    if not spans:
        return text
    out, cursor = [], 0
    for span in spans:
        out.append(text[cursor : span.start()])
        cursor = span.end()
    out.append(text[cursor:])
    return " ".join(out)


def _first_person_density(text: str) -> float:
    """First-person pronouns per 100 words of narration, dialogue removed.
    Dialogue has to go: everyone says "I" inside quotation marks, in every
    book ever written, so leaving it in makes every novel look first-person."""
    narration = _strip_dialogue(text)
    words = narration.split()
    if len(words) < _MIN_NARRATION_WORDS:
        return 0.0
    return len(re.findall(r"\b(?:I|me|my|mine|myself)\b", narration)) / len(words) * 100


def _vocative_in_trailing_position(utterance: str) -> str | None:
    """The vocative from the unambiguous position only, surface form intact.

    Split out from `_vocative` because capitalisation is only evidence *here*.
    A leading vocative sits at the start of a sentence and is capitalised
    whether it is "Conn" or "Boy", so counting those would make every epithet
    look like a name."""
    trailing = re.search(r",\s*(?:my\s+|you\s+)?([A-Za-z][A-Za-z'-]{2,14})\s*[.?!,;]?$", utterance)
    if not trailing:
        return None
    name = trailing.group(1)
    return None if name.lower() in _NOT_A_VOCATIVE else name


def _vocative(utterance: str) -> str | None:
    """The name an utterance addresses, if it plainly addresses one.

    Trailing position ("Come along, boy.") is taken as-is - a comma before the
    final word of an utterance is a vocative and very little else. Leading
    position ("Conn, come here") has to be filtered, because it is also where
    every interjection in English lives ("Well, ...", "Righty-o, ...")."""
    # The terminator may be a comma, not just a full stop: in `"Come along,
    # boy," he said` the comma belongs to the sentence but sits inside the
    # quotation marks. Omitting it silently drops every vocative in an
    # utterance that continues into its attribution - which is most of them.
    trailing = re.search(r",\s*(?:my\s+|you\s+)?([A-Za-z][A-Za-z'-]{2,14})\s*[.?!,;]?$", utterance)
    if trailing:
        name = trailing.group(1)
        if name.lower() not in _NOT_A_VOCATIVE:
            return name.lower()
    leading = re.match(r"([A-Za-z][A-Za-z'-]{2,14}),\s", utterance)
    if leading:
        name = leading.group(1)
        if name.lower() not in _NOT_A_VOCATIVE:
            return name.lower()
    return None


def _speaker(text: str, start: int, end: int) -> str | None:
    """Who said it, from the attribution tag after or before the utterance."""
    after = re.match(r"[,.!?]?\s*" + _SPEAKER + r"\s+(?:\w+ly\s+)?" + _SPEECH_VERBS + r"\b", text[end : end + 70])
    if after:
        return after.group(1)
    before = re.search(_SPEAKER + r"\s+(?:\w+ly\s+)?" + _SPEECH_VERBS + r"\s*,?\s*$", text[max(0, start - 70) : start])
    return before.group(1) if before else None


def auto_link_plan(found: NarratorAliases) -> tuple[list[str], list[str]]:
    """`(names, epithets)` safe to link without asking anyone. Empty when the
    evidence doesn't support a link, which is the common case.

    This is what makes the whole pass worth running. A reader's flow is
    download, ingest, extract - nothing in it goes near a linking command, so a
    feature that waits to be invoked is invisible, which is exactly the fault
    of `doctor --merge-name-variants`.

    **Names need two independent signals, because either alone is wrong.**
    Capitalisation says "proper noun", but `Magister` is capitalised 5/5 in the
    reported book and is Keeston addressing *Nevery* while the narrator stands
    by. A shared string relationship says "variant of the same name", but that
    is only meaningful between two names. Requiring both leaves `Conn` and
    `Connwaer` and rejects `Magister`, which relates to nothing.

    **Epithets ride along on whatever the names produced, and are the larger
    half of the win** - on one real book "boy" (495 references in the text),
    "thief" (136) and "gutterboy" (100) outweigh "Conn" (344) and "Connwaer"
    (162) combined. They are safe because `resolve_entity` matches an alias by
    *exact* `match_key`, so an epithet of "boy" absorbs an entity named "boy"
    and can never reach for "the Skandian boy". `query.select_relevant_facts`
    is the one consumer that would substring-match them, and it deliberately
    never reads this list.

    Never links an epithet on its own. Without a name to attach it to there is
    no evidence about *whose* epithet it is, and a lone "boy" would become a
    character called boy."""
    names = [
        candidate
        for candidate in found.aliases
        if candidate.reads_as_a_name and not candidate.is_anyones_term_of_address
    ]
    linked: list[str] = []
    for index, candidate in enumerate(names):
        if any(
            looks_like_a_name_variant(candidate.name, other.name)
            for position, other in enumerate(names)
            if position != index
        ):
            linked.append(candidate.name)
    if len(linked) < 2:
        return [], []

    epithets = [
        candidate.name
        for candidate in found.aliases
        if not candidate.reads_as_a_name and not candidate.is_anyones_term_of_address
    ]
    return linked, epithets


def _times_speaking(text: str, name: str) -> int:
    """How often a name is the subject of a speech tag.

    The narrator of a first-person book is never one - they are "I" - so a
    candidate that speaks belongs to somebody else. This is what separates a
    real epithet from another character the narrator merely *overheard* being
    addressed, which the speaker split alone cannot do: `"Well, Trammel?"
    Brumbee asked` is correctly attributed to Brumbee, who is correctly not the
    narrator, and is still not addressing the narrator.

    Counted over first-person chapters only. A third-person section names its
    characters in speech tags, so including one would credit the narrator's own
    name to somebody else - measured on the reported book, whose later
    third-person sections made "conn" and "connwaer" look like speakers."""
    return len(re.findall(r"\b" + re.escape(name) + r"\b\s+(?:\w+ly\s+)?" + _SPEECH_VERBS + r"\b", text, re.I)) + len(
        re.findall(_SPEECH_VERBS + r"\s+(?:the\s+)?" + re.escape(name) + r"\b", text, re.I)
    )


def detect_narrator_aliases(chapters: list[Chapter]) -> NarratorAliases:
    """Every name the other characters use for a first-person narrator.

    **Narration mode is judged per chapter, not per book**, and that is a
    safeguard rather than a refinement. The reported book is a five-novel
    omnibus whose later sections switch to a third-person point of view, and in
    those sections "the boy" is a servant rather than the narrator. Judging the
    book as a whole would harvest those chapters' vocatives and attach a
    stranger's epithet to the protagonist - the precise "an epithet is
    chapter-scoped in a way a name isn't" hazard. Per-chapter judgement drops
    them: measured, those two chapters score 0.05 and 0.13 against a threshold
    of 4.0.

    Returns empty aliases for a third-person book. Vocatives are still
    extractable there ("will", "halt", "horace"), but nothing in the text says
    *who* a given "boy" was aimed at, and inventing an answer is how a wrong
    identity gets recorded.

    **Known limit, measured rather than supposed:** the "anyone but the
    narrator is addressing the narrator" step assumes a two-hander, and a
    three-party scene breaks it. In the reported book a guard faces the
    narrator and says "I suppose she will have to see him, Captain" - speaking
    *about* the narrator *to* a third person - and "captain" is harvested as an
    alias. That was 1 wrong out of 7 on that book. It is why this reports for
    review instead of applying anything."""
    pair, _ = _best_quote_pair("\n".join(chapter.text for chapter in chapters))

    first_person_chapters: list[int] = []
    considered = 0
    to_narrator: Counter[str] = Counter()
    by_narrator: Counter[str] = Counter()
    surface_forms: dict[str, Counter[str]] = defaultdict(Counter)

    for chapter in chapters:
        if len(chapter.text.split()) < _MIN_NARRATION_WORDS:
            continue
        considered += 1
        if _first_person_density(chapter.text) < _FIRST_PERSON_PER_100_WORDS:
            continue
        first_person_chapters.append(chapter.index)

        _, spans = _best_quote_pair(chapter.text)
        for span in spans:
            name = _vocative(span.group(1))
            if not name:
                continue
            speaker = _speaker(chapter.text, span.start(), span.end())
            if not speaker:
                continue
            # The narrator speaking names somebody else; anyone else speaking,
            # in a scene the narrator is present for, names the narrator.
            (by_narrator if speaker == "I" else to_narrator)[name] += 1
            if speaker != "I":
                # Surface forms, from the one position where capitalisation is
                # evidence. This is what later sorts a name from an epithet.
                surface = _vocative_in_trailing_position(span.group(1))
                if surface:
                    surface_forms[name][surface] += 1

    first_person_text = "\n".join(
        chapter.text for chapter in chapters if chapter.index in set(first_person_chapters)
    )
    kept: list[AliasCandidate] = []
    ambiguous: list[tuple[str, int, int]] = []
    speakers: list[tuple[str, int, int]] = []
    for name, count in to_narrator.most_common():
        if count < _MIN_TIMES_ADDRESSED:
            continue
        if count <= by_narrator[name]:
            ambiguous.append((name, count, by_narrator[name]))
            continue
        spoken = _times_speaking(first_person_text, name)
        if spoken and count / spoken <= _MIN_ADDRESSED_TO_SPOKEN:
            speakers.append((name, count, spoken))
            continue
        forms = surface_forms[name]
        kept.append(
            AliasCandidate(
                # The form the book actually uses, so a linked alias reads like
                # the book rather than like a lowercased token.
                name=max(forms, key=forms.get) if forms else name,
                times_addressed=count,
                times_capitalised=sum(n for form, n in forms.items() if form[:1].isupper()),
            )
        )

    return NarratorAliases(
        aliases=kept,
        addressed_by_narrator=by_narrator.most_common(),
        ambiguous=ambiguous,
        speakers=speakers,
        first_person_chapters=first_person_chapters,
        chapters_considered=considered,
        quote_style=_quote_style_name(pair),
    )
