"""The ship gate.

Every other part of this project exists so that an answer about chapter N is
safe for someone who has only read to chapter N. These tests are what say it
actually is.

They are deliberately kept out of `tests/test_query.py`, which unit-tests each
query primitive in isolation. These run the whole real path a `bookrag chat`
turn runs - `save_book` -> `extract_book` -> `facts_as_of` ->
`select_relevant_facts` -> `format_context` - because a spoiler leak is an
*interaction* between those steps far more often than a bug inside any one of
them. A filter that is individually correct can still leak through what the
step after it derives from the filtered set.

Two tests carry the guarantee, and they fail for different reasons:

- **The sentinel test** names the leak. Every chapter carries a token that
  appears nowhere else in the book, so a failure says exactly which chapter
  escaped and into which render.
- **The truncated-library equivalence test** is the stronger one and the
  actual gate. It renders chapter N twice - once from a library holding the
  whole book, once from a library that has never seen past chapter N - and
  demands the two be byte-identical. It needs no idea of what a leak looks
  like, so it catches the kinds a sentinel cannot: a chapter *count* in a
  header, a rarity score computed over hidden facts, an entity ordering that
  shifts once a later chapter exists, a bucket boundary that moves. If the two
  renders differ at all, information crossed from the future into the present,
  whether or not it is legible as a spoiler.

Two further tests guard the same promise on paths those two don't reach: a
reader probing for a character who hasn't appeared yet, and a later book in the
series merely existing in the library.
"""

from pathlib import Path

import pytest

from bookrag.extract.pipeline import extract_book
from bookrag.ingest.chapter import Chapter
from bookrag.providers.fake_provider import FakeProvider
from bookrag.query import facts_as_of, format_context, select_relevant_facts
from bookrag.storage import save_book
from tests.helpers import NARRATIVE_PADDING

# One token per chapter, appearing in that chapter and nowhere else. Purely
# alphabetic and capitalized so `FakeProvider` extracts each one as an entity
# (its proper-noun regex is `\b[A-Z][a-z]+\b`, which a digit suffix would
# defeat), and nonsense words so no near-miss of a sentinel can be mistaken for
# the sentinel itself.
_SENTINELS = [
    "Sentinelalfa",
    "Sentinelbravo",
    "Sentinelcharlie",
    "Sentineldelta",
    "Sentinelecho",
    "Sentinelfoxtrot",
    "Sentinelgolf",
    "Sentinelhotel",
    "Sentinelindia",
    "Sentineljuliett",
]

# Lowercase throughout, so the only proper nouns in a chapter are the recurring
# protagonist and that chapter's sentinel. Each carries a distinctive noun the
# statement-matching retrieval tier can find.
_EVENTS = [
    "crossed the frostbound estuary",
    "bartered for a brass lantern",
    "deciphered the tide almanac",
    "wintered among the salt farmers",
    "was named harbourmaster",
    "burned the old charts",
    "confessed to the smugglers",
    "inherited the slate quarry",
    "abandoned the northern route",
    "was buried beneath the lighthouse",
]


def _chapters(start: int = 0, stop: int = len(_SENTINELS)) -> list[Chapter]:
    """A book where chapter i's text is traceable to chapter i and nothing
    else. Maren recurs in every chapter so the entity-matching retrieval tier
    has a real subject; because she shares each sentence with that chapter's
    sentinel, her facts are also the most likely carrier of a leak - a
    statement is stored whole, so a co-mentioned future name rides along inside
    a fact about someone the reader already knows.

    `start`/`stop` slice the material, but the returned chapters are always
    indexed from 0: a book's own chapter numbering starts at its own first
    chapter, and handing `save_book` a book whose chapters begin at index 5
    would be testing a shape the product never produces."""
    return [
        Chapter(i, f"Chapter {i + 1}", f"Maren and {_SENTINELS[source]} {_EVENTS[source]}. {NARRATIVE_PADDING}")
        for i, source in enumerate(range(start, stop))
    ]


# One question per retrieval tier in `select_relevant_facts`, since each tier
# reaches `format_context` with a differently-derived set and so is a separate
# chance to leak: a named entity (tier 1), statement-text matching (tier 2),
# and a broad question that matches nothing and falls back to every fact
# (tier 3 - the largest render, and the one most likely to carry a stray line).
_QUESTIONS = (
    "Tell me about Maren",
    "what happened at the quarry",
    "What has happened so far?",
)

# The subset of the above guaranteed to include the reading position's own
# chapter. The topical question deliberately isn't: past chapter 7 it narrows
# to the quarry, which is the point of it.
_INCLUSIVE_QUESTIONS = ("Tell me about Maren", "What has happened so far?")


def _build_library(root: Path, source: Path, chapters: list[Chapter], **kwargs) -> str:
    book_id = save_book(source, chapters, title=kwargs.pop("title", "The Sentinel Voyages"), root=root, **kwargs)
    extract_book(book_id, FakeProvider(), root=root)
    return book_id


def _render(book_id: str, chapter_index: int, question: str, root: Path) -> str:
    """Exactly what `cli.py`'s chat loop assembles and hands to a provider.
    Kept in one place so these tests can never drift into checking a path the
    product doesn't actually take."""
    facts = facts_as_of(book_id, chapter_index, root=root)
    return format_context(select_relevant_facts(question, facts, root=root), root=root)


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "book.epub"
    path.write_text("x", encoding="utf-8")
    return path


def test_no_chapter_past_the_reading_position_reaches_the_render(tmp_path: Path) -> None:
    """The sentinel half of the gate. For every reading position and every
    retrieval tier, the render must contain the current chapter's token and
    none from a later one."""
    root = tmp_path / "library"
    book_id = _build_library(root, _source(tmp_path), _chapters())

    for position in range(len(_SENTINELS)):
        for question in _QUESTIONS:
            rendered = _render(book_id, position, question, root)

            # Non-vacuity floor: an empty render passes every leak assertion
            # below while telling the reader nothing, so a regression that
            # quietly returned "" would otherwise look like a clean pass.
            assert rendered, f"render at chapter {position} for {question!r} was empty"

            for later, sentinel in enumerate(_SENTINELS[position + 1 :], start=position + 1):
                assert sentinel not in rendered, (
                    f"chapter {later} leaked into a render at chapter {position} "
                    f"for the question {question!r}"
                )

        for question in _INCLUSIVE_QUESTIONS:
            rendered = _render(book_id, position, question, root)
            assert _SENTINELS[position] in rendered, (
                f"chapter {position}'s own content is missing from its render "
                f"for {question!r} - the filter is over-tight, not merely safe"
            )


@pytest.mark.parametrize("position", [0, 1, 4, 8, 9])
def test_a_render_cannot_tell_a_truncated_library_from_a_full_one(tmp_path: Path, position: int) -> None:
    """The stronger half, and the one to keep green at all costs.

    Rendering chapter N from the complete book must be byte-identical to
    rendering it from a library that only ever held chapters 0..N. Any
    difference at all means something downstream of `facts_as_of` derived a
    value from chapters the reader hasn't reached - which is how a filter leaks
    what it removed, even when no later sentence is copied through.

    Separate roots, so each library has its own `entities.json`: the global
    entity registry is the most plausible back channel, since it is written by
    the full extraction and then read at render time by both
    `select_relevant_facts` and `format_context`."""
    source = _source(tmp_path)
    all_chapters = _chapters()

    full_root = tmp_path / "full"
    truncated_root = tmp_path / "truncated"
    full_id = _build_library(full_root, source, all_chapters)
    truncated_id = _build_library(truncated_root, source, all_chapters[: position + 1])

    for question in _QUESTIONS:
        from_full = _render(full_id, position, question, full_root)
        from_truncated = _render(truncated_id, position, question, truncated_root)
        assert from_full == from_truncated, (
            f"a reader at chapter {position} asking {question!r} can tell the rest of "
            f"the book exists\n--- from the full library ---\n{from_full}\n"
            f"--- from a library ending at chapter {position} ---\n{from_truncated}"
        )


def test_asking_about_a_character_who_has_not_appeared_yet_confirms_nothing(tmp_path: Path) -> None:
    """A reader can probe. Naming someone from chapter 9 while reading chapter
    1 must not produce a render that treats them as real - the absence of a
    match is itself the answer, and the fallback to "return every fact" must
    not smuggle them back in."""
    root = tmp_path / "library"
    book_id = _build_library(root, _source(tmp_path), _chapters())

    rendered = _render(book_id, 1, f"Who is {_SENTINELS[9]}?", root)

    assert _SENTINELS[9] not in rendered
    assert _SENTINELS[0] in rendered  # the probe fell back to what IS readable


def test_a_later_book_in_the_series_changes_nothing_about_an_earlier_one(tmp_path: Path) -> None:
    """Ingesting book 2 must not alter a single character of what a reader
    partway through book 1 sees. The shared entity registry makes this a real
    risk rather than a theoretical one: extracting book 2 resolves its names
    against book 1's entities and writes to the same file the render reads."""
    source = _source(tmp_path)
    book_one_chapters = _chapters(stop=5)

    alone_root = tmp_path / "alone"
    book_one_alone = _build_library(
        alone_root, source, book_one_chapters, title="Voyages One", series_name="Voyages", series_position=1
    )

    with_sequel_root = tmp_path / "with-sequel"
    book_one = _build_library(
        with_sequel_root, source, book_one_chapters, title="Voyages One", series_name="Voyages", series_position=1
    )
    _build_library(
        with_sequel_root,
        source,
        _chapters(start=5),
        title="Voyages Two",
        series_name="Voyages",
        series_position=2,
    )

    for question in _QUESTIONS:
        assert _render(book_one, 2, question, with_sequel_root) == _render(
            book_one_alone, 2, question, alone_root
        ), f"book 2's existence is visible to a reader on chapter 2 of book 1, asking {question!r}"
