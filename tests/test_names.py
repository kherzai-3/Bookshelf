"""Covers `bookrag.names` - the residue rule's shared core, and the
personhood test that lets it run at ingest where no entity types exist yet.

`tests/test_library.py` covers the same rule applied to *entity names* through
`doctor`. This file covers it applied to *text*, which is the auto-linking
path: `person_link_groups` is what `cli.auto_link_title_variants` calls, and
`reads_as_a_person` is the guard standing in for `doctor`'s characters-only
restriction.
"""

import pytest

from bookrag.names import (
    AUTOLINK_RATIO,
    PROPOSE_RATIO,
    name_frequencies,
    person_link_groups,
    reads_as_a_person,
    residue_of,
)


def _prose(mentions: dict[str, int], extra: str = "") -> str:
    """Prose mentioning each name exactly as often as asked, each as a
    *maximal* run of capitalised words - the unit the rule compares. Every
    surrounding word is lowercase on purpose: a capitalised one would join the
    run and change the frequency the fixture exists to set."""
    sentences = []
    for name, times in mentions.items():
        sentences.extend([f"and then {name} spoke to the others."] * times)
    return " ".join(sentences) + " " + extra


def _speech(name: str, times: int) -> str:
    return " ".join([f"{name} said nothing at all."] * times)


def test_residue_of_strips_a_title_no_wordlist_contains() -> None:
    """"Magister" is a rank *The Magic Thief* invented, so no closed list can
    hold it. Nothing here classifies the prefix: the link is made because what
    is left behind is a better-attested name in the same book."""
    freq = name_frequencies([_prose({"Nevery": 300, "Magister Nevery": 20})])

    assert residue_of("Magister Nevery", freq) == "Nevery"


def test_residue_of_keeps_a_name_that_stands_on_its_own() -> None:
    freq = name_frequencies([_prose({"Nevery": 300, "Magister Nevery": 20})])

    assert residue_of("Nevery", freq) is None


def test_the_two_paths_disagree_only_where_being_wrong_costs_differently() -> None:
    """The one place the propose and auto-link settings diverge, pinned with
    the real case that motivated the split. *The Magic Thief* writes "Kerrn"
    284 times and "Captain Kerrn" 81 - a ratio of 3.5, so `doctor` offers it
    and ingest does not. Hand-scoring said the link is correct, but the 13
    links that 3x adds across the corpus include 3 wrong ones, and a wrong
    merge applied silently at ingest is a different proposition from one a
    reader declines with a keystroke."""
    freq = name_frequencies([_prose({"Kerrn": 284, "Captain Kerrn": 81})])

    assert residue_of("Captain Kerrn", freq, PROPOSE_RATIO) == "Kerrn"
    assert residue_of("Captain Kerrn", freq, AUTOLINK_RATIO) is None


def test_a_person_is_a_proper_noun_the_book_lets_speak() -> None:
    text = _prose({"Nevery": 300}) + " " + _speech("Nevery", 5)
    freq = name_frequencies([text])

    assert reads_as_a_person("Nevery", text, freq)


def test_a_category_is_rejected_however_often_its_members_speak() -> None:
    """The determiner half of the guard, and the case that needs it. "Gu
    Immortals" is a category whose members talk constantly, so the speech
    signal alone accepts it - measured, that is exactly how "Gu Immortals"
    (14.5% determiner share) and "Gu Masters" (17.9%) got through. A book
    writes "the Gu Immortals" and never "the Fang Yuan"."""
    text = (
        _prose({"Gu Immortals": 300})
        + " ".join([" the Gu Immortals gathered here."] * 200)
        + _speech("Gu Immortals", 40)
    )
    freq = name_frequencies([text])

    assert not reads_as_a_person("Gu Immortals", text, freq)


def test_a_place_is_rejected_however_proper_its_name_looks() -> None:
    """The speech half of the guard. A place name can be as determiner-free as
    a person's - "Earth Trench" is written bare - so the only thing separating
    it from a character is that nobody ever hears it speak."""
    text = _prose({"Earth Trench": 300})
    freq = name_frequencies([text])

    assert not reads_as_a_person("Earth Trench", text, freq)


def test_person_link_groups_gathers_every_decorated_form_of_one_name() -> None:
    """What ingest actually applies. Four decorated forms arrive as one group
    with the bare name canonical, which is the shape `link_names` wants -
    and is 02c(ii) dissolving, since the entity-level ambiguity veto would
    have refused all four."""
    text = (
        _prose(
            {
                "Fang Yuan": 900,
                "Lord Fang Yuan": 30,
                "Elder Fang Yuan": 25,
                "Gu Yue Fang Yuan": 20,
                "Venerable Fang Yuan": 15,
            }
        )
        + _speech("Fang Yuan", 20)
    )

    (group,) = person_link_groups([text])

    assert group.name == "Fang Yuan"
    assert group.decorated == [
        "Elder Fang Yuan",
        "Gu Yue Fang Yuan",
        "Lord Fang Yuan",
        "Venerable Fang Yuan",
    ]


def test_person_link_groups_keeps_two_people_of_one_clan_apart() -> None:
    text = (
        _prose(
            {
                "Fang Yuan": 900,
                "Gu Yue Fang Yuan": 20,
                "Elder Fang Yuan": 20,
                "Fang Zheng": 600,
                "Gu Yue Fang Zheng": 25,
                "Elder Fang Zheng": 15,
            }
        )
        + _speech("Fang Yuan", 20)
        + _speech("Fang Zheng", 20)
    )

    groups = person_link_groups([text])

    assert [group.name for group in groups] == ["Fang Yuan", "Fang Zheng"]
    assert groups[0].decorated == ["Elder Fang Yuan", "Gu Yue Fang Yuan"]
    assert groups[1].decorated == ["Elder Fang Zheng", "Gu Yue Fang Zheng"]


def test_person_link_groups_says_nothing_about_a_book_of_categories() -> None:
    """Nonfiction, and the reason auto-linking is safe to run on every book.
    Measured, the rule proposes nothing at all on either nonfiction title in
    the corpus; here the same shape is checked directly - a qualified variety
    of a category is exactly the residue rule's known failure, and the
    personhood guard is what stops it being applied."""
    text = _prose({"Elixir": 400, "Blue Elixir": 30, "Violet Elixir": 25}) + " ".join(
        [" the Elixir was expensive."] * 120
    )

    assert person_link_groups([text]) == []


@pytest.mark.parametrize("ratio", [PROPOSE_RATIO, AUTOLINK_RATIO])
def test_a_one_off_decorated_form_is_never_linked(ratio: float) -> None:
    """"Demon King Fang Yuan" occurs once in 2,360 chapters, and was twice
    cited as a worked example of the title problem. A form seen once is a
    typo, an extraction artefact or a one-time flourish."""
    freq = name_frequencies([_prose({"Fang Yuan": 900, "Demon King Fang Yuan": 1})])

    assert residue_of("Demon King Fang Yuan", freq, ratio) is None
