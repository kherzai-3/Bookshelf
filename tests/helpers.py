"""Shared test fixtures: synthetic epub/pdf builders, reused across test modules
so each loader/CLI test doesn't hand-roll its own sample book."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from ebooklib import epub

from bookrag.ingest.consolidate import CONSOLIDATION_MEDIAN_WORDS_THRESHOLD

# Padding for synthetic single-sentence "chapter" text used across
# extraction/query tests - long enough to clear pipeline.py's
# MIN_NARRATIVE_WORDS floor (20 words) without FakeProvider mistaking any of
# it for a new entity: every sentence starts with one of FakeProvider's own
# pronoun stopwords, and no other word here is capitalized.
NARRATIVE_PADDING = (
    "It was a quiet day. He said nothing more. She had already left. "
    "They walked in silence. We waited outside."
)


def _bulk_filler(min_words: int) -> str:
    """Same proper-noun-free, FakeProvider-safe padding as NARRATIVE_PADDING,
    repeated until it clears min_words - used to keep a fixture's two
    "chapters" each safely above CONSOLIDATION_MEDIAN_WORDS_THRESHOLD, so
    ingest.consolidate doesn't merge them into one for tests that assume
    two distinct chapters and have nothing to do with consolidation itself
    (that's build_fragmented_epub's job)."""
    words = (NARRATIVE_PADDING + " ").split()
    repeated = words * (min_words // len(words) + 1)
    return " ".join(repeated[:min_words])


# Comfortably above CONSOLIDATION_MEDIAN_WORDS_THRESHOLD so build_sample_epub/
# build_narrative_epub's two "chapters" are never merged by ingest.consolidate.
_UNCONSOLIDATED_CHAPTER_WORDS = CONSOLIDATION_MEDIAN_WORDS_THRESHOLD + 100


def build_sample_epub(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Test Book")
    book.set_language("en")
    book.add_author("Test Author")

    c1 = epub.EpubHtml(title="Chapter One", file_name="chap1.xhtml")
    c1.content = f"<html><body><h1>Chapter One</h1><p>The hero arrives. {_bulk_filler(_UNCONSOLIDATED_CHAPTER_WORDS)}</p></body></html>"
    c2 = epub.EpubHtml(title="Chapter Two", file_name="chap2.xhtml")
    c2.content = f"<html><body><h1>Chapter Two</h1><p>The hero leaves. {_bulk_filler(_UNCONSOLIDATED_CHAPTER_WORDS)}</p></body></html>"

    book.add_item(c1)
    book.add_item(c2)
    book.toc = (c1, c2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2]

    epub.write_epub(str(path), book)


def build_narrative_epub(path: Path) -> None:
    """Like build_sample_epub, but with chapter paragraphs long enough to
    clear pipeline.py's MIN_NARRATIVE_WORDS floor - for tests that need
    extraction to actually run against a chapter's text, not just ingestion."""
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Test Book")
    book.set_language("en")
    book.add_author("Test Author")

    c1 = epub.EpubHtml(title="Chapter One", file_name="chap1.xhtml")
    c1.content = (
        "<html><body><h1>Chapter One</h1><p>Will walked slowly through the "
        "quiet forest at dawn, listening carefully for any sign of danger "
        f"along the narrow, winding path ahead of him. {_bulk_filler(_UNCONSOLIDATED_CHAPTER_WORDS)}"
        "</p></body></html>"
    )
    c2 = epub.EpubHtml(title="Chapter Two", file_name="chap2.xhtml")
    c2.content = (
        "<html><body><h1>Chapter Two</h1><p>Halt quietly handed Will the "
        "silver oakleaf without a word, marking him at last as a fully "
        f"fledged ranger of the kingdom. {_bulk_filler(_UNCONSOLIDATED_CHAPTER_WORDS)}"
        "</p></body></html>"
    )

    book.add_item(c1)
    book.add_item(c2)
    book.toc = (c1, c2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2]

    epub.write_epub(str(path), book)


# Narration dense enough in first-person pronouns to clear vocatives.py's
# threshold (4.0 per 100 words of narration; this runs ~16) and long enough to
# clear its 50-word narration floor. Proper-noun-free, like NARRATIVE_PADDING,
# so the only names in a first-person fixture are the ones its dialogue puts
# there.
_I_NARRATE = (
    "I walked back through the market with my hands pushed into my pockets. "
    "I had nothing left to trade and I knew it perfectly well. The stalls were "
    "closing around me and I watched the lamps go out one by one while I waited "
    "for my chance to slip away. I counted over what I still had, which was "
    "nothing at all, and I went on anyway because I could not think what else "
    "I might usefully do with my evening. "
)


def build_first_person_epub(path: Path) -> None:
    """A first-person novel whose dialogue calls its narrator by two spellings
    of one name and by an epithet - the shape `ingest.vocatives` looks for, and
    the only fixture that exercises auto-linking at ingest end to end.

    Every utterance is spoken by a *named* character (never "I"), because that
    is the whole signal: in a first-person book an utterance from anyone but the
    narrator is, in a two-hander, addressed to the narrator. The names sit in
    trailing position with their capitalisation intact, since that is the one
    position where a capital distinguishes a name from an epithet - so "Conn"
    and "Connwaer" read as names and "boy" reads as an epithet, exactly as they
    do in the real book this is shaped from."""
    book = epub.EpubBook()
    book.set_identifier("first-person-id")
    book.set_title("First Person Book")
    book.set_language("en")
    book.add_author("First Person Author")

    # Both name spellings and the epithet clear vocatives.py's floor of 2
    # sightings in each chapter, so neither chapter carries the link alone.
    dialogue = (
        "“You are late, Conn,” Nevery said. "
        "“I had expected you an hour ago, Connwaer,” Nevery said. "
        "“Come along, boy,” Nevery said. "
        "“Do not touch that, Conn,” Nevery said. "
        "“Wipe your feet, Connwaer,” Nevery said. "
        "“Sit down, boy,” Nevery said."
    )
    narration = _I_NARRATE * 9  # ~800 words, over the consolidation threshold

    items = []
    for number, title in enumerate(("Chapter One", "Chapter Two"), start=1):
        chapter = epub.EpubHtml(title=title, file_name=f"chap{number}.xhtml")
        chapter.content = f"<html><body><h1>{title}</h1><p>{narration}{dialogue}</p></body></html>"
        book.add_item(chapter)
        items.append(chapter)

    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]

    epub.write_epub(str(path), book)


def build_titled_character_epub(path: Path) -> None:
    """A *third-person* novel that calls one character by a bare name and by
    an invented rank - the shape `names.person_link_groups` looks for, and the
    only fixture exercising third-person auto-linking at ingest end to end.

    Deliberately not first person, so `ingest.vocatives` stays silent and the
    link can only have come from the residue rule. "Magister" is not in
    `library._TITLES` on purpose: a rank a wordlist already contains would not
    prove anything this feature adds.

    The counts matter and are not arbitrary. The bare name has to clear 100
    sightings and outnumber the decorated form five times over (the
    auto-linking ratio), the decorated form has to clear 10, and the character
    has to be caught speaking at least three times - otherwise
    `reads_as_a_person` cannot tell him from a place."""
    book = epub.EpubBook()
    book.set_identifier("titled-character-id")
    book.set_title("Titled Character Book")
    book.set_language("en")
    book.add_author("Titled Character Author")

    bare = "Nevery walked the length of the hall in silence. " * 80
    decorated = "Magister Nevery frowned at the locked door. " * 10
    # Determiner-free and caught speaking: the two signals that separate a
    # person from a place when no entity types exist yet.
    speaking = "Nevery said nothing at all about it. " * 4
    text = bare + decorated + speaking + NARRATIVE_PADDING

    items = []
    for number, title in enumerate(("Chapter One", "Chapter Two"), start=1):
        chapter = epub.EpubHtml(title=title, file_name=f"chap{number}.xhtml")
        chapter.content = f"<html><body><h1>{title}</h1><p>{text}</p></body></html>"
        book.add_item(chapter)
        items.append(chapter)

    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]

    epub.write_epub(str(path), book)


def build_fragmented_epub(path: Path, fragment_count: int = 40, words_per_fragment: int = 100) -> None:
    """A page-scanned-style epub: many small, untitled spine documents with
    no heading markup at all - mirrors a real Internet-Archive-produced
    book (one physical page per spine file) that needs
    ingest.consolidate.consolidate_fragments to be extractable well."""
    book = epub.EpubBook()
    book.set_identifier("fragmented-id")
    book.set_title("Fragmented Book")
    book.set_language("en")
    book.add_author("Fragmented Author")

    items = []
    for i in range(fragment_count):
        page = epub.EpubHtml(file_name=f"page{i}.xhtml")
        words = " ".join(f"word{i}-{w}" for w in range(words_per_fragment))
        page.content = f"<html><body><p>{words}</p></body></html>"
        book.add_item(page)
        items.append(page)

    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]

    epub.write_epub(str(path), book)


def build_sample_pdf(path: Path) -> None:
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Chapter One\nThe hero arrives.")
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Chapter Two\nThe hero leaves.")
    doc.set_toc([[1, "Chapter One", 1], [1, "Chapter Two", 2]])
    doc.set_metadata({"title": "Test PDF Book", "author": "Test PDF Author"})
    doc.save(str(path))
    doc.close()
