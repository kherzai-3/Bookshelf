"""Find the separately-published books stitched together inside one file.

A bindup, a "complete collection" or a fan-compiled series epub is one file
holding several real books end to end. Ingested whole it produces one book
with five "Chapter 1"s, and every chapter number the tool reports afterwards
is a number the reader cannot find in their own copy: `--chapter 40` means
nothing to someone on chapter 6 of book 3. Spoiler scoping is coarser than it
looks for the same reason - "up to chapter 40" spans two books.

The signal is the file's own table of contents. Every omnibus in the corpus
nests its chapters under one TOC section per book, and that section's spine
items give the span directly. The work here is not finding those sections -
`ebooklib` hands them over - it is refusing the ones that are not books.

**Three conditions, and Moby Dick fails two of them independently.** Project
Gutenberg's Moby Dick has five nested TOC sections ("ETYMOLOGY.", "CHAPTER
100. Leg and Arm.", "Epilogue", ...) which are typesetting artifacts, not
volumes. Taking nesting at face value would shatter a single novel into five
"books", which is the worst outcome this detector can produce - far worse
than leaving an omnibus whole, because it is silent and the reader has no
reason to suspect it. So a candidate set must (1) not overlap, (2) cover
nearly all of the book's text, and (3) hold a real book's worth of words
each. Measured on the library:

    book                 volumes  overlap  coverage  smallest volume
    Ranger's Apprentice        2       no     98.4%     64,897 words
    The Magic Thief            5       no     99.9%      7,405 words
    Reverend Insanity         24       no    100.0%     73,051 words
    Moby Dick                  5      YES     45.2%                -

Moby Dick is rejected twice over: two of its sections resolve to the same
spine item, and even setting that aside its sections hold under half the
text. The three books that are omnibuses pass all three checks with no
margin worth worrying about. The Eye of the World, The Perfect Run and
Atomic Habits have no nested sections at all and never reach the checks.

`MIN_VOLUME_WORDS` is set by a real volume, not by a guess: "The Magic
Thief: A Proper Wizard" is a published novella of 7,405 words sitting
between three full novels, so the floor has to stay well under that while
still rejecting a section that is only a dedication page.

**epub only.** A PDF outline can nest too, but `pdf_loader` already
flattens to level-1 entries, so a nested PDF arrives here as one "chapter"
per volume and there is nothing left to detect. That is a real gap, not a
decision that PDFs never come as omnibuses.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from ebooklib import epub

from bookrag.ingest.chapter import Chapter

# Two books is an omnibus; one is a book.
MIN_VOLUMES = 2

# Well under the smallest real volume in the corpus (7,405 words) and well
# over a dedication page, a map or a copyright notice - the section shapes
# that would otherwise be minted as their own book.
MIN_VOLUME_WORDS = 1000

# The volumes must account for essentially the whole file. What is left over
# is dropped as front and back matter, so this doubles as a bound on how much
# text a split is allowed to discard. Real omnibuses measure 98.4-100%;
# Moby Dick's spurious sections measure 45.2%.
MIN_TEXT_COVERAGE = 0.85

_ORDINAL = r"(?:\d{1,3}|[ivxlIVXL]{1,6}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"

# "Book 1: The Ruins of Gorlan" -> "The Ruins of Gorlan". Deliberately
# requires a number (or roman/spelled-out equivalent) after the keyword, so
# "Book of the New Sun" is left alone - matching a bare word after "Book"
# would strip the title's own first word.
_VOLUME_LABEL = re.compile(rf"^\s*(?:book|volume|vol\.?|part)\s+{_ORDINAL}\b\s*[:.–—-]?\s*", re.IGNORECASE)


@dataclass(frozen=True)
class Volume:
    """One real book inside the file, as a span of loaded chapter indices."""

    title: str
    label: str  # the table-of-contents heading, verbatim
    start: int  # first chapter index, inclusive
    end: int  # last chapter index, inclusive
    words: int


@dataclass(frozen=True)
class OmnibusPlan:
    volumes: list[Volume]
    chapter_count: int
    total_words: int
    covered_words: int

    @property
    def coverage(self) -> float:
        return self.covered_words / self.total_words if self.total_words else 0.0

    @property
    def dropped_chapters(self) -> int:
        """Chapters outside every volume: covers, a shared contents page, an
        about-the-author, a preview of the next book. They are discarded, and
        `MIN_TEXT_COVERAGE` is what keeps that from ever being much."""
        inside = sum(volume.end - volume.start + 1 for volume in self.volumes)
        return self.chapter_count - inside

    @property
    def dropped_words(self) -> int:
        return self.total_words - self.covered_words


def detect_volumes(
    path: str | Path,
    chapters: list[Chapter],
    chapter_sources: list[str | None],
    book_title: str,
) -> OmnibusPlan | None:
    """The books inside `path`, or None if it holds one book (the usual case).

    `chapter_sources[i]` is the spine document chapter `i` came from, which is
    what ties a TOC entry to a chapter index - the loader splits some spine
    documents at internal headings, so the two lists are not one-to-one and
    the mapping cannot be reconstructed from the epub alone.

    `book_title` is used only to name a volume the TOC labels by number alone
    ("Volume 7"), which would otherwise become a book called "Volume 7".
    """
    if Path(path).suffix.lower() != ".epub" or not chapters:
        return None

    first_seen: dict[str, int] = {}
    last_seen: dict[str, int] = {}
    for index, source in enumerate(chapter_sources):
        if source is None:
            continue
        key = _normalize(source)
        first_seen.setdefault(key, index)
        last_seen[key] = index
    if not first_seen:
        return None

    book = epub.read_epub(str(path))
    spans: list[tuple[int, int, str]] = []
    for label, hrefs in _top_level_sections(book.toc):
        touched = [key for key in (_normalize(href) for href in hrefs) if key in first_seen]
        if not touched:
            continue
        spans.append((min(first_seen[k] for k in touched), max(last_seen[k] for k in touched), label))

    if len(spans) < MIN_VOLUMES:
        return None
    spans.sort()

    # Two sections resolving into the same chapters are not two books - they
    # are two anchors inside one document. This is the check Moby Dick trips.
    if any(spans[i][1] >= spans[i + 1][0] for i in range(len(spans) - 1)):
        return None

    words = [len(chapter.text.split()) for chapter in chapters]
    volumes = [
        Volume(
            title=_volume_title(label, book_title),
            label=label,
            start=start,
            end=end,
            words=sum(words[start : end + 1]),
        )
        for start, end, label in spans
    ]
    if any(volume.words < MIN_VOLUME_WORDS for volume in volumes):
        return None

    total = sum(words)
    covered = sum(volume.words for volume in volumes)
    if not total or covered / total < MIN_TEXT_COVERAGE:
        return None

    return OmnibusPlan(
        volumes=volumes, chapter_count=len(chapters), total_words=total, covered_words=covered
    )


def volume_chapters(chapters: list[Chapter], volume: Volume) -> list[Chapter]:
    """One volume's chapters, re-indexed from 0 - so each book counts its own
    chapters, which is the entire point of splitting."""
    return [
        Chapter(index=i, title=chapter.title, text=chapter.text)
        for i, chapter in enumerate(chapters[volume.start : volume.end + 1])
    ]


def _top_level_sections(toc) -> list[tuple[str, list[str]]]:
    """Each depth-0 nested TOC group, with every href at or under it.

    Only depth 0: a volume is never nested inside another volume, and Magic
    Thief's "A Guide to People and Places" is a nested group *within* book 5
    that must not be mistaken for a sixth book."""
    sections: list[tuple[str, list[str]]] = []
    for entry in toc:
        if not isinstance(entry, tuple):
            continue
        section, children = entry
        hrefs = [getattr(section, "href", None)]
        _collect_hrefs(children, hrefs)
        sections.append((str(getattr(section, "title", "") or ""), [h for h in hrefs if h]))
    return sections


def _collect_hrefs(entries, out: list) -> None:
    for entry in entries:
        if isinstance(entry, tuple):
            section, children = entry
            out.append(getattr(section, "href", None))
            _collect_hrefs(children, out)
        else:
            out.append(getattr(entry, "href", None))


def _normalize(href: str) -> str:
    """A TOC href and a spine item's name refer to the same document through
    different spellings: the href carries the anchor the entry points at
    ("text/part0079.html#2BASE0-..."), and either may be percent-encoded."""
    return posixpath.normpath(unquote(href).split("#")[0])


def _volume_title(label: str, book_title: str) -> str:
    stripped = _VOLUME_LABEL.sub("", label).strip()
    if stripped:
        return stripped
    # Nothing but an ordinal ("Volume 7"), which is not a title anyone could
    # find in a library listing. Qualify it with the file's own title.
    return f"{book_title} {label.strip()}".strip() or label.strip()
