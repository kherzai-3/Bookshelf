"""Covers `bookrag.locate`: turning a fact into a place a reader can go.

Two things are being guarded, and only one of them is "does it find the
passage". The other is **does it refuse to guess**, which matters more: a
citation that points at the wrong sentence tells a reader the book says
something it does not, and they have no way to tell that from a correct one.
Both defects these tests pin were found by running the matcher against real
extractor output rather than against invented statements - see the module's
context doc for the measurement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bookrag.ingest.chapter import Chapter
from bookrag.locate import Citation, cite, cite_facts, find_passage, volume_at
from bookrag.query import Fact
from bookrag.storage import save_book

# Deliberately repeats "Choosing Day" the way the real chapter does. IDF is
# computed over the chapter's own sentences, so a term the book leans on is
# correctly worth little - and a four-sentence fixture where every term is
# unique would make common words look maximally rare and quietly test a
# scoring regime that never occurs in a real book. The first version of this
# fixture did exactly that and disagreed with the measured result it was
# written to pin.
CHAPTER = (
    # A decoy carrying every word of the next sentence except the name, and
    # placed first so that ties resolve to it. Without the capitalised-
    # stopword rule the name is discarded and this is what a search for Will
    # returns.
    "Horace examined the target he had been shooting at, and frowned. "
    "Halt examined the target Will had been shooting at, and nodded. "
    "The boy had grouped every arrow inside the inner ring. "
    # Split across two sentences on purpose, with neither half naming both
    # things, so only a two-sentence window can carry the whole statement.
    "Halt drew his saxe knife. The blade caught the firelight. "
    "Baron Arald was the Lord of Redmont Fief, and the wards were raised by his generosity. "
    "Tomorrow would be the biggest day in his life, because tomorrow was the Choosing Day. "
    "Every ward waited for the Choosing Day with the same dread. "
    "No ward had ever slept the night before a Choosing Day. "
    "The Choosing Day would decide where each of them spent the rest of the day. "
    "By the end of that day the Choosing would be over and done."
)


@pytest.fixture
def library(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "book.epub"
    source.write_text("x", encoding="utf-8")
    root = tmp_path / "library"
    book_id = save_book(
        source,
        [
            Chapter(index=0, title="Chapter One", text=CHAPTER),
            Chapter(index=1, title="Chapter Two", text="Morgarath revealed the Kalkara to his lieutenants."),
        ],
        title="The Ruins of Gorlan",
        root=root,
    )
    return root, book_id


# --------------------------------------------------------------------------
# finding the passage
# --------------------------------------------------------------------------


def test_a_paraphrase_finds_the_sentence_it_came_from() -> None:
    passage = find_passage("Baron Arald was the Lord of Redmont Fief.", CHAPTER)

    assert passage is not None
    assert "Baron Arald was the Lord of Redmont Fief" in passage.quote


def test_a_statement_whose_distinctive_words_are_absent_gets_no_quote() -> None:
    """The regression test for the worst match the real sample produced.

    "Will had not had a 'growing spurt' before Choosing Day" scored a perfect
    1.00 against a sentence about tomorrow being the biggest day of his life.
    Two bugs compounded: the protagonist's name was discarded as the modal
    verb "will", and words the chapter never uses were dropped from the
    denominator as well as the numerator - so the statement was scored only
    on "choosing" and "day", which did match, and nothing was left to say the
    passage was wrong."""
    assert find_passage("Will had not had a growing spurt before Choosing Day.", CHAPTER) is None


def test_a_capitalised_stopword_is_read_as_a_name() -> None:
    """"Will" is both the protagonist and a modal verb. Dropping it as a
    stopword throws away the single most identifying word in a sentence about
    him."""
    passage = find_passage("Will had been shooting at the target.", CHAPTER)

    assert passage is not None
    # The decoy sentence carries every other word of the statement, so the
    # name is the only thing that can tell them apart.
    assert "Will had been shooting at" in passage.quote
    assert "Horace examined the target" not in passage.quote


def test_a_sentence_initial_capital_does_not_mint_a_name() -> None:
    """Sentence-initial capitalisation is free and proves nothing - otherwise
    every chapter opening "Will you come?" would treat the modal verb as a
    character and match it against every mention of one."""
    from bookrag.locate import names_in

    assert "will" not in names_in("Will you come tomorrow? Will it rain?")
    assert "will" in names_in("Halt told Will to come tomorrow.")


def test_the_name_is_learned_from_the_chapter_not_the_statement() -> None:
    """An extractor writes "Will was small and wiry" - the name lands in the
    one position where a capital is free, so the statement alone can never
    prove it is a name. The chapter can, and does."""
    from bookrag.locate import _content_words, names_in

    statement = "Will had been shooting at the target."

    assert "will" not in _content_words(statement)
    assert "will" in _content_words(statement, names_in(CHAPTER))


def test_words_the_chapter_never_uses_count_against_the_match() -> None:
    """The mechanism behind the abstention above, pinned on its own so a
    future change to `_UNSEEN_IDF` cannot quietly restore the old behaviour."""
    shared_only = find_passage("Choosing Day.", CHAPTER)
    with_absent_words = find_passage("Choosing Day at Castle Araluen with Gilan and Crowley.", CHAPTER)

    assert shared_only is not None
    assert with_absent_words is None or with_absent_words.score < shared_only.score


def test_a_paraphrase_spanning_two_sentences_is_found() -> None:
    """A fact routinely restates two adjacent sentences as one. The quote has
    to cover both, or it points at half the evidence."""
    passage = find_passage("Halt drew his saxe knife and the blade caught the firelight.", CHAPTER)

    assert passage is not None
    assert "Halt drew his saxe knife" in passage.quote
    assert "The blade caught the firelight" in passage.quote


def test_a_long_quote_is_trimmed_but_stays_searchable() -> None:
    long_text = "Halt said " + "the quick brown fox jumped over the lazy dog " * 20
    passage = find_passage("Halt said the quick brown fox jumped.", long_text)

    assert passage is not None
    assert len(passage.quote) <= 224
    # The head must survive verbatim, because that is what a reader pastes
    # into a search box.
    assert passage.quote.startswith("Halt said the quick brown fox")


# --------------------------------------------------------------------------
# rendering the location
# --------------------------------------------------------------------------


def _citation(**kwargs) -> Citation:
    base = dict(
        book_title="A Book",
        volume=None,
        volume_chapter=None,
        chapter_index=3,
        chapter_title=None,
        pages=None,
        passage=None,
        position=None,
    )
    return Citation(**{**base, **kwargs})


def test_pages_outrank_a_chapter_title() -> None:
    """Real case: every chapter of *Finite and Infinite Games* has a title and
    all of them are meaningless PDF bookmark IDs ("FAIG0080"). A title-only
    citation would look informative and be useless; the page range is what a
    reader can act on."""
    assert _citation(chapter_title="FAIG0080", pages=[79, 85]).where() == "A Book, pp. 79-85"
    assert _citation(chapter_title="FAIG0080", pages=[79, 79]).where() == "A Book, p. 79"


def test_a_chapter_title_is_used_when_there_are_no_pages() -> None:
    assert _citation(chapter_title="Chapter Fourteen").where() == "A Book, Chapter Fourteen"


def test_a_book_with_neither_still_gets_a_location() -> None:
    assert _citation().where() == "A Book, chapter 3"


def test_a_volume_is_named_rather_than_the_file_it_was_stitched_into() -> None:
    """"The Burning Bridge, Chapter Fourteen" is usable; "Ranger's Apprentice
    1 & 2 Bindup, chapter 48" is the thing the reader was trying to get away
    from. The book is stored whole either way - this is the entire
    user-visible payoff of detecting the volumes."""
    citation = _citation(
        book_title="Ranger's Apprentice 1 & 2 Bindup",
        volume="The Burning Bridge",
        volume_chapter=14,
        chapter_title="Chapter Fourteen",
    )

    assert citation.where() == "The Burning Bridge, Chapter Fourteen"


def test_an_untitled_chapter_in_a_volume_counts_from_the_volume_start() -> None:
    """The fallback rung, and the one that has to do arithmetic. A reader
    holding book 2 opens it at chapter 1; "chapter 48" is the file's number
    and appears in no copy of the book they own."""
    citation = _citation(book_title="A Bindup", volume="The Burning Bridge", volume_chapter=14, chapter_index=48)

    assert citation.where() == "The Burning Bridge, chapter 14"


def test_position_is_shown_only_when_there_is_no_page_number() -> None:
    """A percentage is a coarse stand-in for a page. Showing both is noise,
    and the page is strictly better."""
    assert "40% in" in _citation(chapter_title="Chapter One", position=0.4).where()
    assert "%" not in _citation(pages=[12, 12], position=0.4).where()


def test_the_quote_is_what_the_render_leads_to() -> None:
    passage = find_passage("Baron Arald was the Lord of Redmont Fief.", CHAPTER)
    rendered = _citation(chapter_title="Chapter One", passage=passage).render()

    assert rendered.startswith("A Book, Chapter One - \"")
    assert "Redmont Fief" in rendered


# --------------------------------------------------------------------------
# reading the library
# --------------------------------------------------------------------------


def test_cite_reads_the_book_and_finds_the_passage(library) -> None:
    root, book_id = library

    citation = cite(book_id, 0, "Baron Arald was the Lord of Redmont Fief.", root=root)

    assert citation is not None
    assert citation.book_title == "The Ruins of Gorlan"
    assert citation.chapter_title == "Chapter One"
    assert citation.passage is not None


def test_cite_never_reads_a_chapter_other_than_the_one_asked_for(library) -> None:
    """The spoiler property, as behaviour rather than as an implementation
    detail. `tests/test_spoiler_safety.py` proves it end to end; this says
    which function is responsible."""
    root, book_id = library

    citation = cite(book_id, 0, "Morgarath revealed the Kalkara to his lieutenants.", root=root)

    assert citation is not None
    assert "Kalkara" not in citation.render()
    assert "Morgarath" not in citation.render()


def test_cite_returns_nothing_for_a_book_that_is_not_there(tmp_path: Path) -> None:
    assert cite("no-such-book", 0, "anything", root=tmp_path) is None


def test_cite_facts_keeps_the_order_it_was_given(library) -> None:
    root, book_id = library
    facts = [
        Fact(book_id=book_id, entity_id="e1", chapter_index=1, category="event", statement="Morgarath and the Kalkara."),
        Fact(book_id=book_id, entity_id="e2", chapter_index=0, category="event", statement="Baron Arald of Redmont."),
    ]

    cited = cite_facts(facts, root=root)

    assert [fact.chapter_index for fact, _ in cited] == [1, 0]
    assert all(isinstance(citation, Citation) for _, citation in cited)


def test_cite_facts_drops_a_fact_whose_chapter_is_missing(library) -> None:
    """A source line that cannot say where it points is not worth a line."""
    root, book_id = library
    facts = [Fact(book_id=book_id, entity_id="e1", chapter_index=99, category="event", statement="Nothing.")]

    assert cite_facts(facts, root=root) == []


def test_a_chapter_with_pages_cites_them(tmp_path: Path) -> None:
    """The page-scanned and PDF path, end to end through storage - the two
    books in the corpus with no usable chapter titles at all."""
    source = tmp_path / "book.pdf"
    source.write_text("x", encoding="utf-8")
    root = tmp_path / "library"
    book_id = save_book(
        source,
        [Chapter(index=0, title="FAIG0080", text=CHAPTER, pages=[79, 85])],
        title="Finite and Infinite Games",
        root=root,
    )

    citation = cite(book_id, 0, "Baron Arald was the Lord of Redmont Fief.", root=root)

    assert citation is not None
    assert citation.pages == [79, 85]
    assert citation.where() == "Finite and Infinite Games, pp. 79-85"


def test_pages_survive_a_save_and_load_cycle(tmp_path: Path) -> None:
    """`pages` is a list rather than a tuple precisely so this holds - a tuple
    is written as a JSON array and read back as a list, which would make the
    same chapter compare unequal to itself."""
    source = tmp_path / "book.pdf"
    source.write_text("x", encoding="utf-8")
    root = tmp_path / "library"
    book_id = save_book(source, [Chapter(index=0, title=None, text="Text.", pages=[3, 9])], title="B", root=root)

    record = json.loads((root / book_id / "chapters.jsonl").read_text(encoding="utf-8").splitlines()[0])

    assert record["pages"] == [3, 9]


# --------------------------------------------------------------------------
# the volume map
# --------------------------------------------------------------------------


VOLUMES = [
    {"title": "The Ruins of Gorlan", "label": "Book 1", "start": 2, "end": 40},
    {"title": "The Burning Bridge", "label": "Book 2", "start": 41, "end": 80},
]


def test_a_chapter_is_placed_in_its_volume_and_renumbered() -> None:
    assert volume_at(VOLUMES, 41) == ("The Burning Bridge", 1)
    assert volume_at(VOLUMES, 48) == ("The Burning Bridge", 8)
    assert volume_at(VOLUMES, 2) == ("The Ruins of Gorlan", 1)


def test_a_chapter_outside_every_volume_has_none() -> None:
    """Front matter, a shared contents page, an about-the-author. The split
    this replaced deleted these chapters; they are kept now, so a citation
    has to have something to say about them - the file's own title."""
    assert volume_at(VOLUMES, 0) is None
    assert volume_at(VOLUMES, 99) is None
    assert volume_at(None, 3) is None


def test_a_bindup_cites_the_volume_end_to_end(tmp_path: Path) -> None:
    """Through storage, which is where this has to work: the volume map is
    written by ingest and read back by `cite` from `metadata.json`."""
    source = tmp_path / "bindup.epub"
    source.write_text("x", encoding="utf-8")
    root = tmp_path / "library"
    chapters = [Chapter(index=i, title=None, text="Filler.") for i in range(4)]
    chapters[3] = Chapter(index=3, title=None, text=CHAPTER)
    book_id = save_book(
        source,
        chapters,
        title="Ranger's Apprentice 1 & 2 Bindup",
        volumes=[{"title": "The Burning Bridge", "label": "Book 2", "start": 2, "end": 3}],
        root=root,
    )

    citation = cite(book_id, 3, "Baron Arald was the Lord of Redmont Fief.", root=root)

    assert citation is not None
    assert citation.volume == "The Burning Bridge"
    assert citation.where().startswith("The Burning Bridge, chapter 2")
    assert "Bindup" not in citation.render()
