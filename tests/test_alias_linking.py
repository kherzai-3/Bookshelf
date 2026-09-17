"""Covers linking a narrator's several names into one character automatically,
across the three modules that have to agree for it to be safe:
`ingest.vocatives` decides what to link, `extract.resolve` applies it, and
`query` deliberately declines to.

The first test in this file is the load-bearing one. Everything else here is
support for it.
"""

from pathlib import Path

import pytest

from bookrag.extract.resolve import resolve_entity, save_entities, seed_alias_group
from bookrag.ingest.vocatives import AliasCandidate, NarratorAliases, auto_link_plan
from bookrag.query import Fact, select_relevant_facts


def _candidate(
    name: str,
    times_addressed: int = 4,
    times_capitalised: int = 0,
    chapters: set[int] | None = None,
    times_in_trailing_position: int | None = None,
) -> AliasCandidate:
    """`times_in_trailing_position` defaults to `times_addressed`, i.e. a
    candidate seen only in trailing position - which is what the corpus
    overwhelmingly contains (every real candidate on all eight books except
    `Conn` has the two counts equal). Pass it explicitly to describe a candidate
    the book also addresses at the start of an utterance; that gap is what
    `reads_as_a_name` measures and is covered end to end, against the real
    detector rather than a hand-built candidate, by
    `test_vocatives.py::test_a_leading_sighting_does_not_dilute_the_capitalisation_ratio`."""
    return AliasCandidate(
        name,
        times_addressed,
        times_capitalised,
        times_addressed if times_in_trailing_position is None else times_in_trailing_position,
        chapters or set(),
    )


def _a_name(name: str, times: int = 4, chapters: set[int] | None = None) -> AliasCandidate:
    """A vocative capitalised every time it was seen in trailing position."""
    return _candidate(name, times, times, chapters)


def _narrator(*aliases: AliasCandidate) -> NarratorAliases:
    return NarratorAliases(aliases=list(aliases), first_person_chapters=[0], chapters_considered=1)


def _library_with_a_linked_narrator(root: Path) -> tuple[str, str]:
    """Conn, answering to "Connwaer" and referred to as "boy", plus a second
    character who has nothing to do with him. Returns both entity ids.

    The second character matters: `select_relevant_facts` falls back to
    returning *every* fact when a question names no entity at all, so a test
    asserting "this question did not retrieve Conn" needs the question to
    retrieve somebody, or it passes for the wrong reason."""
    entities: dict = {"entities": []}
    conn_id, _ = seed_alias_group(entities, "book", ["Conn", "Connwaer"], epithets=["boy"])
    benet_id = resolve_entity("Benet", "character", "book", entities)
    save_entities(entities, root)
    return conn_id, benet_id


def _facts(*entity_ids: str) -> list[Fact]:
    return [
        Fact(book_id="book", entity_id=entity_id, chapter_index=0, category="development", statement=f"About {entity_id}.")
        for entity_id in entity_ids
    ]


def test_an_epithet_resolves_an_extracted_fact_but_never_answers_a_question(tmp_path: Path) -> None:
    """**The whole safety property of epithets, in one test.**

    `aliases` and `epithets` exist as separate fields because the two consumers
    of a name match differently. `resolve_entity` compares exact `match_key`s,
    so an epithet of "boy" absorbs a fact the model filed under "boy" and can
    never reach for a different boy - that is worth ~750 references on one real
    book. `select_relevant_facts` substring-matches against a question, where
    the same epithet would drag the narrator into every question containing the
    word.

    Adding `epithets` to `select_relevant_facts`'s candidate list is the single
    change that silently undoes this, and it is a one-word edit that looks like
    a bug fix. This test exists to fail when somebody makes it.
    """
    conn_id, benet_id = _library_with_a_linked_narrator(tmp_path)
    entities = {
        "entities": [
            {
                "entity_id": conn_id,
                "canonical_name": "Conn",
                "type": "character",
                "aliases": ["Connwaer"],
                "epithets": ["boy"],
                "book_ids": ["book"],
            }
        ]
    }

    # Extraction: a fact the model filed under the epithet lands on Conn,
    # instead of creating a second character called "boy".
    assert resolve_entity("boy", "character", "book", entities) == conn_id
    assert len(entities["entities"]) == 1

    # Retrieval: a question about somebody else's boy does not.
    retrieved = select_relevant_facts(
        "Who is the boy that Benet trained?", _facts(conn_id, benet_id), root=tmp_path
    )

    assert [f.entity_id for f in retrieved] == [benet_id]


def test_an_alias_answers_a_question_where_an_epithet_does_not(tmp_path: Path) -> None:
    """The other half of the split: `aliases` reach both consumers, so asking
    about the narrator under either spelling of his name still works. Without
    this, the test above could be satisfied by dropping epithets entirely -
    which is the design that was rejected."""
    conn_id, benet_id = _library_with_a_linked_narrator(tmp_path)
    facts = _facts(conn_id, benet_id)

    assert [f.entity_id for f in select_relevant_facts("Tell me about Conn", facts, root=tmp_path)] == [conn_id]
    assert [f.entity_id for f in select_relevant_facts("Tell me about Connwaer", facts, root=tmp_path)] == [conn_id]


def test_a_capitalised_vocative_reads_as_a_name_and_a_lowercase_one_does_not() -> None:
    """What sorts the two lists. Measured in trailing position only, where a
    capital means something - real counts from the reported book were Connwaer
    24/24 and Conn 22/22 against boy 1/106, lad 0/14, thief 0/3."""
    assert _candidate("Connwaer", times_addressed=24, times_capitalised=24).reads_as_a_name
    assert not _candidate("boy", times_addressed=106, times_capitalised=1).reads_as_a_name

    # Conn is the case the denominator distinction exists for: 26 sightings, 22
    # of them trailing and all 22 capitalised. Against every sighting that is
    # 0.85 - still a name, but by 0.05; against the sightings capitalisation was
    # actually counted in, it is 1.00.
    conn = _candidate("Conn", times_addressed=26, times_capitalised=22, times_in_trailing_position=22)
    assert conn.reads_as_a_name
    assert conn.times_capitalised / conn.times_addressed < 1.0


def test_auto_link_plan_links_two_spellings_of_a_name_and_their_epithets() -> None:
    plan = _narrator(_a_name("Conn"), _a_name("Connwaer"), _candidate("boy"), _candidate("lad"))

    assert auto_link_plan(plan) == (["Conn", "Connwaer"], ["boy", "lad"])


def test_auto_link_plan_ignores_a_capitalised_name_that_relates_to_nothing() -> None:
    """Capitalisation alone is not enough, and this is the real case that
    proves it: "Magister" is capitalised 5/5 in the reported book and is
    Keeston addressing *Nevery* while the narrator stands by. It relates to no
    other name, so requiring a shared string relationship rejects it while
    keeping Conn/Connwaer."""
    plan = _narrator(_a_name("Conn"), _a_name("Connwaer"), _a_name("Magister"))

    names, _ = auto_link_plan(plan)

    assert names == ["Conn", "Connwaer"]


def test_auto_link_plan_refuses_a_book_with_two_narrators() -> None:
    """**Two narrators must not become one character.**

    The rule needs a name to have a variant partner, and that was checked
    pairwise against *any* other name - so every survivor was thrown into one
    flat list and declared one person. A book alternating between two
    first-person narrators who each have a spelling variant of their own
    produced `['Conn', 'Connwaer', 'Row', 'Rowena']`: two pairs, silently fused,
    written to `entities.json` at ingest with nobody asked.

    Linking neither is the right answer rather than a cautious one. Nothing in
    the text says which narrator a given epithet belongs to, and the epithets
    are the larger half of the win - see
    `test_auto_link_plan_links_two_spellings_of_a_name_and_their_epithets`.
    """
    plan = _narrator(
        _a_name("Conn"), _a_name("Connwaer"),
        _a_name("Row"), _a_name("Rowena"),
        _candidate("boy"), _candidate("girl"),
    )

    assert auto_link_plan(plan) == ([], [])


def test_auto_link_plan_still_links_one_narrator_beside_an_unrelated_name() -> None:
    """The narrowing above must not cost the normal case. A lone capitalised
    bystander ("Magister") is its own group of one, which never qualifies, so
    the single real pair is still linked - this is the real Magic Thief shape
    and the corpus check depends on it."""
    plan = _narrator(_a_name("Conn"), _a_name("Connwaer"), _a_name("Magister"), _candidate("boy"))

    assert auto_link_plan(plan) == (["Conn", "Connwaer"], ["boy"])


def test_auto_link_plan_surrenders_an_epithet_to_a_rival_narrator() -> None:
    """**The half of the two-narrator bug that grouping does not reach.**

    Refusing a book with two qualifying name *groups* only helps when both
    narrators have a spelling variant. Give the second narrator a single name
    and she forms a group of one, which never qualifies - so the first
    narrator's pair is linked as normal and every epithet in the book rides
    along with it, hers included. `girl` lands on Conn, and because
    `resolve_entity` matches an epithet by exact `match_key`, her facts then
    accumulate on him: a merged identity, which is the failure this module
    treats as unrecoverable everywhere else.

    Her *name* out-claims his on her own chapters, and that is the signal."""
    plan = _narrator(
        _a_name("Conn", chapters={0, 2, 4}),
        _a_name("Connwaer", chapters={0, 2, 4}),
        _candidate("boy", chapters={0, 2, 4}),
        _a_name("Row", chapters={1, 3, 5}),
        _candidate("girl", chapters={1, 3, 5}),
    )

    assert auto_link_plan(plan) == (["Conn", "Connwaer"], ["boy"])


def test_an_epithet_with_no_rival_is_kept_even_sharing_no_chapter_with_a_name() -> None:
    """**The rule has to be comparative, and this is the measurement that says
    so.** The obvious version - keep an epithet only where its chapters
    intersect the linked names' - reads as the safe choice and is wrong. On the
    real book the narrator is addressed by name in only 36 of his 78
    first-person chapters, so chapter overlap largely records which supporting
    character was on stage: `shadow` (what Jaggus calls him) and `cousin` (what
    Embre calls him) share *no* chapter with a name sighting, and the absolute
    rule discarded both. Both are genuinely his, read out of the text.

    With nobody else competing for it, an epithet stays."""
    plan = _narrator(
        _a_name("Conn", chapters={0, 2}),
        _a_name("Connwaer", chapters={0, 2}),
        _candidate("shadow", chapters={7, 9}),
    )

    assert auto_link_plan(plan) == (["Conn", "Connwaer"], ["shadow"])


def test_one_shared_chapter_does_not_hand_an_epithet_to_a_rival() -> None:
    """The same principle as `_MIN_TIMES_ADDRESSED`: a single sighting is not
    evidence. Real case - `cousin` (Embre's term for the narrator) and the known
    false positive `Magister` both appear in chapter 66 and nowhere else
    together, and at a threshold of one shared chapter that coincidence was
    enough to take a genuine epithet off the narrator."""
    plan = _narrator(
        _a_name("Conn", chapters={0, 2}),
        _a_name("Connwaer", chapters={0, 2}),
        _a_name("Magister", chapters={8, 9, 66}),
        _candidate("cousin", chapters={66}),
    )

    assert auto_link_plan(plan) == (["Conn", "Connwaer"], ["cousin"])


def test_auto_link_plan_links_three_spellings_of_one_name_as_one_group() -> None:
    """Grouping is transitive: "Conn", "Connwaer" and "Connwaerdin" are one
    person, and a rule that only grouped the pairs it directly compared would
    split them."""
    plan = _narrator(_a_name("Conn"), _a_name("Connwaer"), _a_name("Connwaerdin"))

    names, _ = auto_link_plan(plan)

    assert names == ["Conn", "Connwaer", "Connwaerdin"]


def test_auto_link_plan_links_nothing_when_only_one_name_is_found() -> None:
    """Two unrelated names are two characters, not one - so with nothing to
    link, the epithets have no owner and must not be linked either. A lone
    "boy" linked to nobody would become a character called boy."""
    plan = _narrator(_a_name("Conn"), _a_name("Magister"), _candidate("boy"))

    assert auto_link_plan(plan) == ([], [])


def test_auto_link_plan_never_links_an_epithet_on_its_own() -> None:
    plan = _narrator(_candidate("boy"), _candidate("lad"), _candidate("thief"))

    assert auto_link_plan(plan) == ([], [])


@pytest.mark.parametrize("term", ["sir", "Dear", "ma'am"])
def test_a_term_of_address_is_never_linked(term: str) -> None:
    """These attach to whoever is being spoken to, so they say nothing about
    who that is. Each one survives the speaker filters on real data by being
    addressed to a third party while the narrator stands by."""
    plan = _narrator(_a_name("Conn"), _a_name("Connwaer"), _a_name(term), _candidate(term.lower()))

    names, epithets = auto_link_plan(plan)

    assert names == ["Conn", "Connwaer"]
    assert epithets == []


def test_seeding_keeps_epithets_out_of_the_alias_list() -> None:
    """The split has to survive the write, not just the read - folding the two
    lists together here would leak epithets into question matching by the back
    door, with `select_relevant_facts` unchanged and its test still passing."""
    entities: dict = {"entities": []}

    entity_id, created = seed_alias_group(entities, "book", ["Conn", "Connwaer"], epithets=["boy", "lad"])

    (entity,) = entities["entities"]
    assert created
    assert entity["entity_id"] == entity_id
    assert entity["canonical_name"] == "Conn"
    assert entity["aliases"] == ["Connwaer"]
    assert entity["epithets"] == ["boy", "lad"]
