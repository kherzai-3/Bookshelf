"""Covers `ingest.vocatives`: reading a narrator's several names out of who
says what to whom, with no model and no extraction.

Every fixture below is shaped from a real measurement on a real book rather
than invented - the numbers each one encodes are in
`context/src/bookrag/ingest/vocatives.py.md`.
"""

from bookrag.ingest.chapter import Chapter
from bookrag.ingest.vocatives import detect_narrator_aliases

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
    assert dict(found.aliases) == {"boy": 2, "conn": 2}


def test_what_the_narrator_calls_other_people_is_not_an_alias() -> None:
    chapters = [
        _chapter(0, _I_NARRATE, *([_said_by_narrator("Good evening, Nevery.")] * 3)),
        _chapter(1, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
    ]

    found = detect_narrator_aliases(chapters)

    assert dict(found.aliases) == {"boy": 2}
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
    assert dict(found.aliases) == {"boy": 2}
    assert "servant" not in dict(found.aliases)


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
    assert dict(found.aliases) == {"boy": 3}


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

    assert dict(found.aliases) == {"boy": 2}


def test_an_interjection_before_a_comma_is_not_a_name() -> None:
    """"Well, ..." and "Yes, ..." occupy the same position as a leading
    vocative, and outnumber real ones: before this filter, "yes" and "well"
    ranked second and third across a whole real book."""
    chapters = [
        _chapter(0, _I_NARRATE, *([_said_by_another("Well, that went badly.")] * 4)),
        _chapter(1, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
    ]

    assert dict(detect_narrator_aliases(chapters).aliases) == {"boy": 2}


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

    assert dict(found.aliases) == {"boy": 2}
    assert [name for name, _, _ in found.speakers] == ["trammel"]


def test_front_matter_is_not_judged_for_narration() -> None:
    chapters = [
        Chapter(0, "Copyright", "All rights reserved."),
        _chapter(1, _I_NARRATE, *([_said_by_another("Come along, boy.")] * 2)),
    ]

    found = detect_narrator_aliases(chapters)

    assert found.chapters_considered == 1
    assert dict(found.aliases) == {"boy": 2}
