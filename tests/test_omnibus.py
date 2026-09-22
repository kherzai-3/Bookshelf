"""Covers `ingest.omnibus` and the split it drives at ingest.

The detector's job is asymmetric, and these tests are weighted accordingly.
Failing to split an omnibus leaves the tool exactly as it was: chapter
numbers a reader cannot find in their own copy. Splitting a book that is not
an omnibus shatters one novel into several, silently, with no signal a reader
could act on. So there are three separate refusal tests - one per guard -
against one happy path, and the refusals use fixtures shaped from the real
book that would trip each guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bookrag.cli import main
from bookrag.ingest import epub_loader, pdf_loader
from bookrag.ingest.chapter import Chapter
from bookrag.ingest.omnibus import (
    MIN_TEXT_COVERAGE,
    MIN_VOLUME_WORDS,
    Volume,
    _volume_title,
    detect_volumes,
    volume_chapters,
)
from bookrag.storage import load_chapters, series_reading_order
from tests.helpers import (
    build_anchored_sections_epub,
    build_omnibus_epub,
    build_sample_epub,
    build_sample_pdf,
    build_thin_sections_epub,
)


@pytest.fixture(autouse=True)
def _library_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "library"
    monkeypatch.setenv("BOOKRAG_LIBRARY_ROOT", str(root))
    return root


def _plan(path: Path, book_title: str = "The File Title"):
    loader = epub_loader if path.suffix == ".epub" else pdf_loader
    sourced = loader.load_chapters_with_sources(path)
    return detect_volumes(
        path,
        [chapter for _source, chapter in sourced],
        [source for source, _chapter in sourced],
        book_title,
    )


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------


def test_nested_toc_sections_are_the_books_inside_the_file(tmp_path: Path) -> None:
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path)

    plan = _plan(path)

    assert plan is not None
    assert [volume.title for volume in plan.volumes] == ["The First Book", "The Second Book"]
    assert [(volume.start, volume.end) for volume in plan.volumes] == [(2, 4), (5, 7)]
    assert plan.dropped_chapters == 3  # two front matter, one back


def test_sections_resolving_into_one_document_are_not_volumes(tmp_path: Path) -> None:
    """The Project Gutenberg Moby Dick case, and the reason this detector is
    not just "does the table of contents nest?". Its sections are anchors in
    one document, so their chapter spans overlap - two books cannot."""
    path = tmp_path / "novel.epub"
    build_anchored_sections_epub(path)

    assert _plan(path) is None


def test_sections_holding_a_minority_of_the_text_are_not_volumes(tmp_path: Path) -> None:
    path = tmp_path / "mostly-loose.epub"
    build_thin_sections_epub(path, sectioned_chapters=2, loose_chapters=6)

    plan = _plan(path)

    assert plan is None
    # Coverage has to be the rule that did it, and the sections have to be
    # big enough that the size floor did not. The first version of this test
    # gave each section one chapter, which put it under MIN_VOLUME_WORDS -
    # so it passed with the coverage check deleted.
    sourced = epub_loader.load_chapters_with_sources(path)
    words = [len(chapter.text.split()) for _source, chapter in sourced]
    assert sum(words[:2]) > MIN_VOLUME_WORDS and sum(words[2:4]) > MIN_VOLUME_WORDS
    assert sum(words[:4]) / sum(words) < MIN_TEXT_COVERAGE


def test_a_section_too_small_to_be_a_book_is_not_one(tmp_path: Path) -> None:
    """A dedication page or a map nested under its own heading is not a
    volume, however cleanly the rest of the file partitions."""
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path, chapters_per_volume=1, front_matter=0, back_matter=0)
    sourced = epub_loader.load_chapters_with_sources(path)
    chapters = [chapter for _source, chapter in sourced]
    sources = [source for source, _chapter in sourced]
    assert all(len(chapter.text.split()) < MIN_VOLUME_WORDS for chapter in chapters)

    assert detect_volumes(path, chapters, sources, "The File Title") is None


def test_a_flat_table_of_contents_is_one_book(tmp_path: Path) -> None:
    path = tmp_path / "sample.epub"
    build_sample_epub(path)

    assert _plan(path) is None


def test_a_pdf_is_never_split(tmp_path: Path) -> None:
    """Not because PDF omnibuses don't exist - `pdf_loader` flattens the
    outline to level 1, so by the time the chapters get here the nesting that
    would identify them is already gone. See ingest/omnibus.py's docstring."""
    path = tmp_path / "sample.pdf"
    build_sample_pdf(path)

    assert _plan(path) is None


def test_a_nested_group_inside_a_volume_is_not_another_volume(tmp_path: Path) -> None:
    """Real case: Magic Thief book 5 nests "A Guide to People and Places"
    *under* its own section, so a recursive scan for nested groups would
    report six books in a five-book collection - and because the appendix
    sits inside book 5's own span, a recursive scan would see an overlap and
    refuse to split the file at all."""
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path, appendix_in_last_volume=2)

    plan = _plan(path)

    assert plan is not None and len(plan.volumes) == 2
    # The appendix belongs to volume 2, not to a volume of its own.
    assert plan.volumes[1].end == 9


def test_volume_chapters_are_renumbered_from_zero() -> None:
    """The whole point of the split: each book counts its own chapters."""
    chapters = [Chapter(index=i, title=f"c{i}", text="word " * 10) for i in range(10)]
    volume = Volume(title="Middle", label="Book 2: Middle", start=4, end=6, words=30)

    extracted = volume_chapters(chapters, volume)

    assert [chapter.index for chapter in extracted] == [0, 1, 2]
    assert [chapter.title for chapter in extracted] == ["c4", "c5", "c6"]


# --------------------------------------------------------------------------
# volume titles
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Book 1: The Ruins of Gorlan", "The Ruins of Gorlan"),
        ("Volume 2 - The Burning Bridge", "The Burning Bridge"),
        ("Part III: Later", "Later"),
        ("Book One: The Start", "The Start"),
        # No ordinal, so nothing is a prefix: these are whole titles.
        ("The Magic Thief: Lost", "The Magic Thief: Lost"),
        ("Book of the New Sun", "Book of the New Sun"),
    ],
)
def test_an_ordinal_prefix_is_stripped_and_nothing_else_is(label: str, expected: str) -> None:
    assert _volume_title(label, "The File Title") == expected


def test_a_label_that_is_only_an_ordinal_is_qualified_with_the_file_title() -> None:
    """Real case: a 24-volume webnovel whose sections are called "Volume 1"
    ... "Volume 24". Stripping the prefix leaves nothing, and a library
    holding a book called "Volume 7" tells a reader nothing at all."""
    assert _volume_title("Volume 7", "Reverend Insanity") == "Reverend Insanity Volume 7"


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------


def test_ingest_splits_an_omnibus_into_separate_books(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path)

    assert main(["ingest", str(path)]) == 0

    index = json.loads((_library_root / "index.json").read_text(encoding="utf-8"))
    assert [b["book_id"] for b in index["books"]] == ["the-first-book", "the-second-book"]
    assert [b["series"]["position"] for b in index["books"]] == [1, 2]
    assert {b["series"]["name"] for b in index["books"]} == {"An Omnibus"}

    # The correctness claim the whole feature rests on: chapter numbering
    # restarts, so "chapter 0" names a chapter in one real book.
    for book_id in ("the-first-book", "the-second-book"):
        assert [chapter.index for chapter in load_chapters(book_id)] == [0, 1, 2]
    assert "2 books stitched into one file" in capsys.readouterr().out


def test_no_split_keeps_the_omnibus_whole(tmp_path: Path, _library_root: Path) -> None:
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path)

    assert main(["ingest", str(path), "--no-split"]) == 0

    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    metadata = json.loads((book_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["chapter_count"] == 9  # every chapter, front and back matter included
    assert metadata["omnibus"] is None


def test_split_volumes_are_a_series_in_reading_order(tmp_path: Path) -> None:
    """Series metadata is how the split stays wired together: extraction seeds
    book 2 with book 1's characters, and `facts_as_of` scopes across the
    series. Splitting without this would isolate five books that share a
    cast."""
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path, volume_labels=("Book 1: Alpha", "Book 2: Beta", "Book 3: Gamma"))

    assert main(["ingest", str(path)]) == 0

    assert series_reading_order("gamma") == ["alpha", "beta", "gamma"]
    assert series_reading_order("alpha") == ["alpha"]


def test_series_position_offsets_the_volumes(tmp_path: Path, _library_root: Path) -> None:
    """A reader who already has books 1-2 and ingests a 3-4 bindup needs the
    volumes to land at 3 and 4, not to collide at 1 and 2."""
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path)

    assert main(["ingest", str(path), "--series", "Araluen", "--series-position", "3"]) == 0

    index = json.loads((_library_root / "index.json").read_text(encoding="utf-8"))
    assert [b["series"]["position"] for b in index["books"]] == [3, 4]
    assert {b["series"]["name"] for b in index["books"]} == {"Araluen"}


def test_only_one_volume_archives_the_source_file(tmp_path: Path, _library_root: Path) -> None:
    """N identical copies of the source buy nothing - nothing reads `source.*`
    after ingest - and cost 296MB on a real 24-volume file."""
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path, volume_labels=("Book 1: Alpha", "Book 2: Beta", "Book 3: Gamma"))

    assert main(["ingest", str(path)]) == 0

    archived = [p.name for p in _library_root.iterdir() if p.is_dir() and (p / "source.epub").exists()]
    assert archived == ["alpha"]
    for book_id in ("beta", "gamma"):
        metadata = json.loads((_library_root / book_id / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["omnibus"]["source_book_id"] == "alpha"
        assert metadata["source_filename"] == "omnibus.epub"


def test_front_and_back_matter_outside_every_volume_is_dropped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deletion, so it is reported. On the real Ranger's Apprentice bindup
    what this drops includes an 8,500-character extract from book 3 that was
    previously catalogued as the ending of book 2."""
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path, front_matter=2, back_matter=1)

    assert main(["ingest", str(path)]) == 0

    output = capsys.readouterr().out
    assert "dropped 3 chapters" in output
    assert "Copyright and contents." not in "".join(
        chapter.text for book_id in ("the-first-book", "the-second-book") for chapter in load_chapters(book_id)
    )


def test_show_reports_which_omnibus_a_book_came_from(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path)
    assert main(["ingest", str(path)]) == 0
    capsys.readouterr()

    assert main(["show", "the-second-book"]) == 0

    output = capsys.readouterr().out
    assert "from: book 2 of 2 in 'An Omnibus'" in output
    assert "archived under 'the-first-book'" in output


def test_a_single_book_is_unchanged_by_all_of_this(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The regression guard for the common case: most books are one book, and
    nothing about their ingest output or metadata should have moved."""
    path = tmp_path / "sample.epub"
    build_sample_epub(path)

    assert main(["ingest", str(path)]) == 0

    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    metadata = json.loads((book_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["omnibus"] is None
    assert metadata["series"] is None
    assert (book_dir / "source.epub").exists()
    output = capsys.readouterr().out
    assert "stitched into one file" not in output
    assert "Next steps:" in output
