"""Covers `ingest.volumes`: finding the separately published books stitched
into one file, and labelling rather than splitting them.

The detector's job is asymmetric, and these tests are weighted accordingly.
Missing an omnibus leaves citations naming the file instead of the book, which
is a worse locator. Inventing volumes in a book that has none puts a wrong
book title on a citation, silently, with no signal a reader could act on. So
there are four separate refusal tests - one per guard - against one happy
path, and the refusals use fixtures shaped from the real book that trips each
guard.

**These tests were rewritten when the split was removed.** The earlier version
asserted that an omnibus became N books in the library; the same detection now
produces a span map and the file stays one book. The detection tests are
unchanged because the detection is unchanged - what moved is everything
downstream of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bookrag.cli import main
from bookrag.ingest import epub_loader, pdf_loader
from bookrag.ingest.chapter import Chapter
from bookrag.ingest.consolidate import consolidate_fragments, fragment_groups
from bookrag.ingest.volumes import (
    MIN_TEXT_COVERAGE,
    MIN_VOLUME_WORDS,
    Volume,
    VolumePlan,
    _volume_title,
    detect_volumes,
    remap,
    volume_boundaries,
)
from bookrag.storage import load_chapters
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
    assert plan.unlabelled_chapters == 3  # two front matter, one back


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


def test_a_pdf_never_reports_volumes(tmp_path: Path) -> None:
    """Not because PDF omnibuses don't exist - `pdf_loader` flattens the
    outline to level 1, so by the time the chapters get here the nesting that
    would identify them is already gone. See ingest/volumes.py's docstring."""
    path = tmp_path / "sample.pdf"
    build_sample_pdf(path)

    assert _plan(path) is None


def test_a_nested_group_inside_a_volume_is_not_another_volume(tmp_path: Path) -> None:
    """Real case: Magic Thief book 5 nests "A Guide to People and Places"
    *under* its own section, so a recursive scan for nested groups would
    report six books in a five-book collection - and because the appendix
    sits inside book 5's own span, a recursive scan would see an overlap and
    reject the file entirely."""
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path, appendix_in_last_volume=2)

    plan = _plan(path)

    assert plan is not None and len(plan.volumes) == 2
    # The appendix belongs to volume 2, not to a volume of its own.
    assert plan.volumes[1].end == 9


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
    ... "Volume 24". Stripping the prefix leaves nothing, and a citation
    reading "Volume 7, chapter 13" names no book at all."""
    assert _volume_title("Volume 7", "Reverend Insanity") == "Reverend Insanity Volume 7"


# --------------------------------------------------------------------------
# surviving consolidation
# --------------------------------------------------------------------------


def _plan_of(*spans: tuple[int, int]) -> VolumePlan:
    volumes = [
        Volume(title=f"Book {i}", label=f"Book {i}", start=start, end=end, words=1000)
        for i, (start, end) in enumerate(spans, start=1)
    ]
    return VolumePlan(volumes=volumes, chapter_count=10, total_words=10_000, covered_words=10_000)


def test_merging_fragments_never_crosses_a_volume_boundary() -> None:
    """A merged chapter spanning two books would be labelled with whichever
    volume won, and a reader sent to the wrong book entirely. The fragments
    here are 2 words each, so word count alone would merge all ten."""
    chapters = [Chapter(index=i, title=None, text=f"fragment {i}") for i in range(10)]
    plan = _plan_of((2, 4), (5, 7))

    groups = fragment_groups(chapters, boundaries=volume_boundaries(plan))

    assert groups == [[0, 1], [2, 3, 4], [5, 6, 7], [8, 9]]
    merged = consolidate_fragments(chapters, boundaries=volume_boundaries(plan))
    assert [chapter.text for chapter in merged][1] == "fragment 2\n\nfragment 3\n\nfragment 4"


def test_the_volume_map_moves_onto_the_merged_chapters() -> None:
    """Consolidation renumbers chapters, so spans recorded against the raw
    fragments are wrong the moment it runs - and wrong quietly, since they
    would still be valid indices into a shorter book."""
    plan = _plan_of((2, 4), (5, 7))

    remapped = remap(plan, [[0, 1], [2, 3, 4], [5, 6, 7], [8, 9]])

    assert [(v.start, v.end) for v in remapped.volumes] == [(1, 1), (2, 2)]
    assert [v.title for v in remapped.volumes] == ["Book 1", "Book 2"]
    assert remapped.chapter_count == 4


def test_a_page_scanned_omnibus_keeps_its_volume_labels(
    tmp_path: Path, _library_root: Path
) -> None:
    """Both halves together, through a real ingest: a bindup whose fragments
    are page-sized is the case where consolidation and volume detection have
    to coexist. No book in the corpus is both, which is exactly why this is a
    fixture and not a measurement."""
    path = tmp_path / "scanned-omnibus.epub"
    # Page-sized fragments (so `should_consolidate` fires) that still add up
    # to a volume clearing MIN_VOLUME_WORDS (so detection fires).
    build_omnibus_epub(path, chapters_per_volume=6, chapter_words=250)

    assert main(["ingest", str(path)]) == 0

    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    metadata = json.loads((book_dir / "metadata.json").read_text(encoding="utf-8"))
    chapters = load_chapters(book_dir.name)
    assert len(chapters) < 15  # fragments really were merged
    volumes = metadata["volumes"]
    assert [v["title"] for v in volumes] == ["The First Book", "The Second Book"]
    # Every merged chapter in a volume holds that volume's text and no other.
    for number, volume in enumerate(volumes, start=1):
        text = " ".join(c.text for c in chapters[volume["start"] : volume["end"] + 1])
        assert f"Volume {number} chapter" in text
        assert f"Volume {3 - number} chapter" not in text


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------


def test_an_omnibus_is_one_book_with_a_map_of_the_books_inside_it(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The change this whole module was rewritten for. An earlier version
    ingested each volume as its own `book_id`; the citation it produced was
    the same string, and the split cost a deletion of every chapter outside a
    volume, a second ingest flag to escape it, and a shared source archive."""
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path)

    assert main(["ingest", str(path)]) == 0

    index = json.loads((_library_root / "index.json").read_text(encoding="utf-8"))
    assert [b["book_id"] for b in index["books"]] == ["an-omnibus"]
    metadata = json.loads((_library_root / "an-omnibus" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["chapter_count"] == 9
    assert [(v["start"], v["end"], v["title"]) for v in metadata["volumes"]] == [
        (2, 4, "The First Book"),
        (5, 7, "The Second Book"),
    ]
    assert "This file holds 2 separately published books" in capsys.readouterr().out


def test_matter_outside_every_volume_is_kept(tmp_path: Path, _library_root: Path) -> None:
    """The split deleted it - on the real Ranger's Apprentice bindup that
    included an 8,500-character extract from book 3. Keeping it costs a
    citation nothing: those chapters are cited by the file's own title."""
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path, front_matter=2, back_matter=1)

    assert main(["ingest", str(path)]) == 0

    text = " ".join(chapter.text for chapter in load_chapters("an-omnibus"))
    assert "Copyright and contents." in text
    assert "About the author." in text


def test_show_lists_the_books_inside_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one place a reader can check the detector's reading of their file
    after ingest has scrolled away."""
    path = tmp_path / "omnibus.epub"
    build_omnibus_epub(path)
    assert main(["ingest", str(path)]) == 0
    capsys.readouterr()

    assert main(["show", "an-omnibus"]) == 0

    output = capsys.readouterr().out
    assert "volumes: 2 separately published books" in output
    assert "chapters 5-7: The Second Book" in output


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
    assert metadata["volumes"] is None
    assert metadata["series"] is None
    assert (book_dir / "source.epub").exists()
    output = capsys.readouterr().out
    assert "separately published books" not in output
    assert "Next steps:" in output
