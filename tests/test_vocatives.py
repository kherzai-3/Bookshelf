"""Covers `ingest.vocatives`: reading a narrator's several names out of who
says what to whom, with no model and no extraction.

Every fixture below is shaped from a real measurement on a real book rather
than invented - the numbers each one encodes are in
`context/src/bookrag/ingest/vocatives.py.md`.
"""

from bookrag.ingest.chapter import Chapter
from bookrag.ingest.vocatives import auto_link_plan, detect_narrator_aliases

# Narration only - no dialogue. Deliberately dense in first-person pronouns
# (the real book runs ~7 per 100 words) and comfortably over the 50-word floor,
# so a fixture never fails the threshold for a reason the test isn't about.
_I_NARRATE = (
    "I walked back through the market with my hands pushed into my pockets. "
    "I had nothing left to trade and I knew it perfectly well. The stalls were "
    "closing around me and I watched the lamps go out one by one while I waited "
    "for my chance to slip away. I counted over what I still had, which was "
    "nothing at all, and I went on anyway because I could not think what else "
    "I might usefully do with my evening."
)

_HE_NARRATES = (
    "Will walked back through the market with his hands pushed into his pockets. "
    "He had nothing left to trade and he knew it perfectly well. The stalls were "
    "closing around him and he watched the lamps go out one by one while he waited "
    "for his chance to slip away. He counted over what he still had, which was "
    "nothing at all, and he went on anyway because he could not think what else "
    "he might usefully do with his evening."
)


def _by_name(found) -> dict[str, int]:
    """`{name: times addressed}`, lowercased. The detector now keeps the surface
    form the book used (so a linked alias reads like the book rather than a
    lowercased token), which these tests mostly don't care about - the ones that
    do assert on `AliasCandidate` directly."""
    return {c.name.lower(): c.times_addressed for c in found.aliases}


def _chapter(index: int, narration: str, *dialogue: str) -> Chapter:
    return Chapter(index, f"Chapter {index}", narration + " " + " ".join(dialogue))


def _said_by_another(utterance: str) -> str:
    return f"“{utterance}” Nevery said."


def _said_by_narrator(utterance: str) -> str:
    return f"“{utterance}” I said."


def test_what_other_characters_call_the_narrator_becomes_an_alias() -> None:
    """The whole mechanism in one test: the split is by *speaker*. An utterance
    from anyone but the narrator is, in a two-hander, addressed to them."""
    chapters = [
        _chapter(0, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
        _chapter(1, _I_NARRATE, *([_said_by_another("You are late, Conn.")] * 2)),
    ]

    found = detect_narrator_aliases(chapters)

    assert found.is_first_person
    assert _by_name(found) == {"boy": 2, "conn": 2}


def test_what_the_narrator_calls_other_people_is_not_an_alias() -> None:
    chapters = [
        _chapter(0, _I_NARRATE, *([_said_by_narrator("Good evening, Nevery.")] * 3)),
        _chapter(1, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
    ]

    found = detect_narrator_aliases(chapters)

    assert _by_name(found) == {"boy": 2}
    assert dict((name, count) for name, count in found.addressed_by_narrator) == {"nevery": 3}


def test_a_third_person_book_yields_nothing(tmp_path=None) -> None:
    """Vocatives are still extractable in third person - the real book gives
    up "will", "halt", "horace" - but nothing in the text says *who* a given
    "boy" was aimed at, and guessing is how a wrong identity is recorded."""
    chapters = [_chapter(i, _HE_NARRATES, _said_by_another("Come along, boy.")) for i in range(3)]

    found = detect_narrator_aliases(chapters)

    assert not found.is_first_person
    assert found.aliases == []


def test_a_third_person_chapter_inside_a_first_person_book_contributes_nothing() -> None:
    """The safeguard that makes this usable on the book that prompted it. That
    book is a five-novel omnibus whose later sections switch to a third-person
    narrator, and there "the boy" is a servant, not the protagonist. Judging
    narration per book instead of per chapter would attach a stranger's epithet
    to the protagonist - the exact "an epithet is chapter-scoped in a way a name
    isn't" hazard."""
    chapters = [
        _chapter(0, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
        _chapter(1, _HE_NARRATES, *([_said_by_another("Fetch the trunk, servant.")] * 5)),
    ]

    found = detect_narrator_aliases(chapters)

    assert found.first_person_chapters == [0]
    assert _by_name(found) == {"boy": 2}
    assert "servant" not in _by_name(found)


def test_curly_single_quotes_are_found_too() -> None:
    """A real trap, hit while measuring: The Magic Thief uses curly doubles and
    Ranger's Apprentice curly singles. A hardcoded pair does not error, it
    returns zero spans - which reads exactly like "this book has no dialogue"
    and nearly got recorded as a finding about third-person novels."""
    chapters = [
        _chapter(i, _I_NARRATE, "‘Come along, boy,’ Nevery said. ‘It isn’t safe here.’")
        for i in range(3)
    ]

    found = detect_narrator_aliases(chapters)

    assert found.quote_style == "curly single"
    assert _by_name(found) == {"boy": 3}


def test_a_name_the_narrator_uses_for_others_more_often_is_dropped() -> None:
    """Attribution is not perfect - a misread speech tag drops a stray count in
    the wrong column - so the rule is comparative rather than absolute. Real
    case: "nevery" landed 2 against the narrator and 12 in his own mouth."""
    chapters = [
        _chapter(0, _I_NARRATE, *([_said_by_narrator("Good evening, Nevery.")] * 4)),
        _chapter(1, _I_NARRATE, *([_said_by_another("Thank you, Nevery.")] * 2)),
    ]

    found = detect_narrator_aliases(chapters)

    assert found.aliases == []
    assert found.ambiguous == [("nevery", 2, 4)]


def test_a_single_sighting_is_not_evidence() -> None:
    """The trailing-vocative shape also matches an utterance that merely ends
    in ", <word>." Real one-offs harvested from the reported book include
    "hurry", "quiet" and "stoichiometry"; every genuine alias cleared 2."""
    chapters = [
        _chapter(0, _I_NARRATE, _said_by_another("Get down there, quick.")),
        _chapter(1, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
    ]

    found = detect_narrator_aliases(chapters)

    assert _by_name(found) == {"boy": 2}


def test_an_interjection_before_a_comma_is_not_a_name() -> None:
    """"Well, ..." and "Yes, ..." occupy the same position as a leading
    vocative, and outnumber real ones: before this filter, "yes" and "well"
    ranked second and third across a whole real book."""
    chapters = [
        _chapter(0, _I_NARRATE, *([_said_by_another("Well, that went badly.")] * 4)),
        _chapter(1, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
    ]

    assert _by_name(detect_narrator_aliases(chapters)) == {"boy": 2}


def test_a_candidate_who_also_speaks_is_another_character() -> None:
    """The failure the speaker split alone cannot see, and the one that made
    the first measurement look better than it was. In a first-person novel the
    narrator constantly *overhears* other people talking to each other, so
    "spoken by someone other than the narrator" does not mean "addressed to the
    narrator". Real case: `"Well, Trammel?" Brumbee asked` is correctly
    attributed to Brumbee, who is correctly not the narrator, and is still
    addressing Trammel.

    The narrator is never a speech-tag subject - they are "I" - so a name
    caught speaking belongs to somebody else. On the reported book this removed
    every confirmed error (trammel 0.12, argent 0.16, you 0.29, captain 0.75)
    and kept every confirmed alias (connwaer 24.0, boy 5.6, conn 4.3)."""
    chapters = [
        _chapter(
            i,
            _I_NARRATE,
            _said_by_another("What do you think, Trammel?"),
            "“I think not,” Trammel said. “Nor does anyone else.”",
            "“It is late,” Trammel said. “We should go.”",
            _said_by_another("Come along, boy."),
        )
        for i in range(2)
    ]

    found = detect_narrator_aliases(chapters)

    assert _by_name(found) == {"boy": 2}
    assert [name for name, _, _ in found.speakers] == ["trammel"]


def test_capitalisation_sorts_a_name_from_an_epithet_in_trailing_position() -> None:
    """The name/epithet split, measured on real detector output rather than on a
    hand-built `AliasCandidate`.

    This whole file had no capitalisation coverage, which mattered because two
    functions have to agree to produce the ratio: `_vocative` counts the
    sighting and `_vocative_in_trailing_position` decides whether it was
    capitalised. They carried byte-identical copies of the same pattern and the
    same stoplist, so a change to one silently measured the numerator over a
    different set of sightings than the denominator. `_vocative` now delegates,
    and this is what fails if that is ever undone."""
    chapters = [
        _chapter(
            i,
            _I_NARRATE,
            _said_by_another("You are late, Conn."),
            _said_by_another("Come along, boy."),
        )
        for i in range(2)
    ]

    found = detect_narrator_aliases(chapters)
    by_name = {c.name: c for c in found.aliases}

    assert by_name["Conn"].times_capitalised == by_name["Conn"].times_addressed == 2
    assert by_name["Conn"].reads_as_a_name
    assert by_name["boy"].times_capitalised == 0
    assert not by_name["boy"].reads_as_a_name


def test_a_vocative_introduced_by_you_or_my_is_still_the_same_sighting() -> None:
    """"..., you thief." and "..., my boy." are the two determiner forms the
    trailing pattern explicitly allows, and nothing covered them.

    They are the sharpest test of the coupling: `_vocative` counts the sighting
    and `_vocative_in_trailing_position` decides whether it was capitalised, so
    if only one of them knows about `you `/`my ` the two disagree about which
    word the vocative even *is* - `_vocative` returns "thief" while the other
    returns nothing, and the name/epithet ratio is computed over a set of
    sightings that never happened. Verified by sabotage: dropping `you\\s+` from
    one copy of the pattern fails this test and nothing else in the suite."""
    chapters = [
        _chapter(
            i,
            _I_NARRATE,
            _said_by_another("Get down here, you thief."),
            _said_by_another("Steady on, my Conn."),
        )
        for i in range(2)
    ]

    by_name = {c.name: c for c in detect_narrator_aliases(chapters).aliases}

    assert by_name["thief"].times_addressed == 2
    assert by_name["thief"].times_capitalised == 0
    assert by_name["Conn"].times_addressed == by_name["Conn"].times_capitalised == 2


def test_the_surface_form_the_book_used_is_what_gets_reported() -> None:
    """A linked alias has to read like the book, not like a lowercased token -
    it ends up in `entities.json` as a name a reader can ask questions about.
    The surface form only survives via the trailing-position path, so this also
    pins that `_vocative` and `_vocative_in_trailing_position` agree about
    *which* sightings they saw."""
    chapters = [_chapter(i, _I_NARRATE, *([_said_by_another("Wipe your feet, Connwaer.")] * 2)) for i in range(2)]

    (candidate,) = detect_narrator_aliases(chapters).aliases

    assert candidate.name == "Connwaer"


def test_each_candidate_records_the_chapters_it_was_addressed_in() -> None:
    """`auto_link_plan` tells one addressee from another by comparing chapter
    sets, so this is the evidence that rule runs on. Recorded for the
    to-narrator direction only - what the narrator calls other people says
    nothing about who is being addressed."""
    chapters = [
        _chapter(0, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
        _chapter(1, _I_NARRATE, *([_said_by_another("You are late, Conn.")] * 2)),
        _chapter(2, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
    ]

    by_name = {c.name: c for c in detect_narrator_aliases(chapters).aliases}

    assert by_name["boy"].chapters == {0, 2}
    assert by_name["Conn"].chapters == {1}


def test_a_second_narrators_epithet_does_not_land_on_the_first() -> None:
    """**The two-narrator bug end to end, through the real detector.**

    Two first-person narrators in alternating chapters. The second is called
    only "Row", so her name forms a group of one and never qualifies - the
    refusal that catches two *groups* never fires, the first narrator's pair is
    linked as normal, and before this every epithet in the book rode along with
    it. "girl" became one of Conn's names.

    The unit-level version of this lives in `test_alias_linking.py`; this one
    exists because that one builds `AliasCandidate`s by hand, and so cannot
    catch the detector failing to record chapters in the first place."""
    conn = [
        _chapter(index, _I_NARRATE,
                 _said_by_another("Come along, boy."),
                 _said_by_another("You are late, Conn."),
                 _said_by_another("Wipe your feet, Connwaer."))
        for index in (0, 2, 4)
    ]
    row = [
        _chapter(index, _I_NARRATE,
                 _said_by_another("Come along, girl."),
                 _said_by_another("You are late, Row."))
        for index in (1, 3, 5)
    ]

    found = detect_narrator_aliases(sorted(conn + row, key=lambda c: c.index))
    names, epithets = auto_link_plan(found)

    # Both narrators' vocatives are harvested - the detector cannot tell whose
    # chapter is whose, and that pooling is the bug.
    assert {"Conn", "Connwaer", "Row", "boy", "girl"} <= {c.name for c in found.aliases}
    assert names == ["Conn", "Connwaer"]
    assert epithets == ["boy"]


def test_front_matter_is_not_judged_for_narration() -> None:
    chapters = [
        Chapter(0, "Copyright", "All rights reserved."),
        _chapter(1, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
    ]

    found = detect_narrator_aliases(chapters)

    assert found.chapters_considered == 1
    assert _by_name(found) == {"boy": 2}
