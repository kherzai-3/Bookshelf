"""Getting a book's text into units an extraction call can actually handle,
from either direction.

`consolidate_fragments` merges *up*: a book whose loader output is
real-page-sized rather than real-chapter-sized gets its fragments joined until
they are big enough to extract coherently from. That runs at **ingest**, because
it changes what a chapter is - for the reader, for citations, for
`chat --chapter N`.

`split_for_extraction` is the missing symmetric half, splitting *down* for a
chapter too large to extract from in one call. It runs at **extract** time and
changes nothing that is stored: see its own docstring for why that distinction
is load-bearing rather than incidental."""

from __future__ import annotations

from bookrag.ingest.chapter import Chapter

# Real observed data: Ranger's Apprentice (fine as a real chapter list even
# though most of its own fragments are untitled) has a median chapter word
# count around 1900; Atomic Habits (needs this - one real page per fragment,
# from a page-scanned Internet Archive epub) has a median of 313. 600 sits
# comfortably below any real chapter seen so far and above genuinely
# page-sized fragments - triggering on fragment *size*, not title-presence,
# so a book like Ranger's Apprentice (mostly untitled, but reasonably sized)
# is never touched by this.
CONSOLIDATION_MEDIAN_WORDS_THRESHOLD = 600

# Midpoint of the chapter sizes that have worked well for extraction so far
# (~1500-3000 words, see extract/pipeline.py's context doc).
CONSOLIDATION_TARGET_WORDS = 2000


def should_consolidate(chapters: list[Chapter]) -> bool:
    """Median, not mean - a few outlier long/short fragments (front matter,
    a single huge chapter) shouldn't skew the decision either way."""
    if not chapters:
        return False
    word_counts = sorted(len(c.text.split()) for c in chapters)
    median = word_counts[len(word_counts) // 2]
    return median < CONSOLIDATION_MEDIAN_WORDS_THRESHOLD


def fragment_groups(
    chapters: list[Chapter],
    target_words: int = CONSOLIDATION_TARGET_WORDS,
    boundaries: frozenset[int] = frozenset(),
) -> list[list[int]]:
    """Which input fragments end up in which merged chapter, as indices.

    Split out from `consolidate_fragments` so a caller holding spans over the
    *input* indices can move them onto the output - `ingest.volumes.remap` is
    the one caller, turning "book 3 is chapters 40-79" into the same statement
    about merged chapters. Returning indices rather than chapters keeps that
    honest: a `Chapter.index` is set by whoever built it and may or may not be
    its position in this list.
    """
    groups: list[list[int]] = []
    buffer: list[int] = []
    for position, chapter in enumerate(chapters):
        if buffer and position in boundaries:
            groups.append(buffer)
            buffer = []
        buffer.append(position)
        if sum(len(chapters[i].text.split()) for i in buffer) >= target_words:
            groups.append(buffer)
            buffer = []
    if buffer:
        groups.append(buffer)
    return groups


def consolidate_fragments(
    chapters: list[Chapter],
    target_words: int = CONSOLIDATION_TARGET_WORDS,
    boundaries: frozenset[int] = frozenset(),
) -> list[Chapter]:
    """Greedily merges consecutive fragments until reaching target_words,
    re-indexing from 0, purely by word count - a fragment's title is never
    treated as a forced boundary. Real, observed reason this matters: an
    earlier version of this function *did* respect a real title as a forced
    boundary (on the theory that a book mixing some titled, some untitled
    fragments should never merge across a genuine chapter break) - this
    backfired completely on a real book (Finite and Infinite Games, PDF-
    sourced) whose TOC assigns every single fragment a title, but they're
    meaningless internal bookmark IDs ("FAIG0001", "FAIG0002", ...), not
    real chapter headings (the exact "PDF whose TOC entries are meaningless
    internal bookmark IDs" case already documented as a known limitation in
    pdf_loader.py). Since every fragment had *some* title, the old logic
    force-flushed after every single one, silently producing zero merging
    (146 fragments in, 146 "chapters" out) despite should_consolidate
    correctly deciding merging was needed. `should_consolidate` already
    established these fragments are too small to be coherent extraction
    units regardless of what they're titled - once that decision is made,
    title text isn't a reliable-enough signal to override it. Does not
    merge a trailing under-sized remainder backward into the previous
    chapter - extract.pipeline.MIN_NARRATIVE_WORDS and the extraction
    prompt's own non-narrative self-censoring already provide a safety net
    for a genuinely tiny leftover.

    `boundaries` names input positions that must begin a new chapter whatever
    the word count says. Only `ingest.volumes` passes any: merging the last
    page of one book in a bindup onto the first page of the next produces a
    chapter that belongs to two books at once."""
    merged: list[Chapter] = []
    for group in fragment_groups(chapters, target_words, boundaries):
        buffer = [chapters[i] for i in group]
        merged.append(
            Chapter(
                index=len(merged),
                title=next((c.title for c in buffer if c.title), None),
                text="\n\n".join(c.text for c in buffer),
                pages=_merged_pages(buffer),
            )
        )
    return merged


# Whether extract_book splits an oversized chapter at all. **Off**, and off on
# measured evidence rather than caution - the mechanism works, it is the
# decision rule that does not exist yet.
#
# Six oversized chapters of The Eye of the World, whole vs split, same model
# and prompt (coverage = share of statements locate.find_passage can quote):
#
#     ch    words   coverage    entities    near-dups   time
#     104   3,945   24 -> 42%   13 -> 16     0 -> 37    2.21x
#      20   4,078   38 -> 66%   15 -> 20     2 ->  2    1.03x
#      32   4,308   46 -> 50%   23 -> 13     5 -> 22    1.08x
#      62   4,563   28 -> 24%    5 ->  5   113 -> 147   0.86x
#      54   4,959   50 -> 73%    7 -> 14     6 ->  2    0.93x
#      42   5,172   30 -> 69%   14 ->  7   122 -> 21    0.72x
#     mean          +18 points      -0.3        -2.8    1.14x
#
# Citation coverage improves in 5 of 6 and is the only near-consistent signal;
# entities and near-duplicates average to roughly nothing while swinging hard
# both ways. A rule was proposed from the first five - "split when the whole
# chapter saturates the maxItems ceiling", which ch42 and ch54 support strongly
# - and ch62 killed it: it saturated too, and is the one chapter where
# splitting cost coverage, with groundedness falling 0.921 -> 0.647. Word count
# does not separate the wins either (best at 4,959 and 5,172, worst at 4,563).
#
# So: 48 of Eye of the World's 108 chapters would change behaviour on evidence
# that is 5-for-6 at best. Flip this to True to turn it on; the threshold and
# overlap below are already set from the measurement.
SPLIT_OVERSIZED_CHAPTERS = False

# Above this, a chapter is split into pieces before being handed to the model.
# Set from the corpus rather than picked: measured across all eight books here,
# only The Eye of the World (~5,900 words per chapter) and a handful of
# outliers in The Perfect Run, Moby Dick and the Magic Thief omnibus exceed
# this - so six of eight books are untouched, and the two that aren't are
# exactly the ones whose chapters were being truncated by the schema's 40-fact
# ceiling. Comfortably above CONSOLIDATION_TARGET_WORDS (2000), so a chapter
# this module just *built* is never immediately taken apart again.
SPLIT_THRESHOLD_WORDS = 3500

# Target size of each piece. Not much below the threshold on purpose: the
# measured citation damage grows as pieces get smaller (at 600 words, 3 of 72
# quotes were lost outright), and the point is to make an oversized chapter
# tractable, not to chunk everything finely.
SPLIT_TARGET_WORDS = 1800

# Text repeated from the end of one piece at the start of the next. Measured,
# not assumed: at 800-word pieces, going from no overlap to 150 words took
# statements whose quote was lost from 2 to 0. A paraphrase routinely draws on
# a sentence either side of a boundary, and without overlap neither piece
# contains the whole of it.
SPLIT_OVERLAP_WORDS = 150


def split_for_extraction(
    text: str,
    target_words: int = SPLIT_TARGET_WORDS,
    overlap_words: int = SPLIT_OVERLAP_WORDS,
    threshold_words: int | None = None,
) -> list[str]:
    """`text` in pieces small enough to extract from, or `[text]` unchanged.

    **This never changes what a chapter is.** The caller
    (`extract.pipeline.extract_book`) makes one provider call per piece and
    records every resulting fact against the chapter's own index, so
    `chapter_index` still means what it always did. That is what keeps
    `facts_as_of`'s spoiler filtering, `locate.cite`'s citations,
    `volume_at`'s spans and `chat --chapter N` all completely untouched by
    this - and why the split deliberately does not happen at ingest, where it
    would change every one of them and require re-ingesting the library.

    Splits only on paragraph boundaries, so a piece never begins or ends
    mid-sentence. Paragraphs are found with `splitlines()` rather than by
    splitting on a blank line, because the two sources disagree: `epub_loader`
    emits newline-joined paragraphs while `consolidate_fragments` above joins
    its fragments with a blank line. Splitting on `"\\n\\n"` alone silently
    yields one piece for every ordinary epub chapter - it looks like a clean
    result and does nothing.

    A chapter at or under `threshold_words` is returned as a single piece,
    byte-identical, so the overwhelmingly common case is provably unaffected.

    `threshold_words=None` means "use the project's configured behaviour",
    which is what `extract_book` passes and is currently **off** - see
    `SPLIT_OVERSIZED_CHAPTERS` for the measurement behind that. Passing an
    explicit threshold opts in regardless, which is how the tests exercise the
    real splitting and how a measurement harness can evaluate it without
    flipping a global.
    """
    if threshold_words is None:
        if not SPLIT_OVERSIZED_CHAPTERS:
            return [text]
        threshold_words = SPLIT_THRESHOLD_WORDS
    if len(text.split()) <= threshold_words:
        return [text]

    paragraphs = [p for p in text.splitlines() if p.strip()]
    if len(paragraphs) < 2:
        # One unbroken wall of text - there is no boundary to cut on that
        # wouldn't land mid-sentence, and a mid-sentence cut is worse than a
        # prompt that is merely large.
        return [text]

    pieces: list[str] = []
    buffer: list[str] = []
    count = 0
    for paragraph in paragraphs:
        buffer.append(paragraph)
        count += len(paragraph.split())
        if count >= target_words:
            pieces.append("\n".join(buffer))
            buffer, count = _overlap_tail(buffer, overlap_words)
    # `count > overlap_words` rather than `buffer`: after a flush the buffer
    # holds only the carried-over overlap, and emitting that as a final piece
    # would re-send text the previous piece already covered, with nothing new.
    if buffer and count > overlap_words:
        pieces.append("\n".join(buffer))
    return pieces or [text]


def _overlap_tail(buffer: list[str], overlap_words: int) -> tuple[list[str], int]:
    """The trailing paragraphs to carry into the next piece, and their length.

    Whole paragraphs, never a partial one - the overlap exists so a paraphrase
    spanning a boundary still has both halves somewhere, and half a paragraph
    reintroduces the problem it is there to solve.
    """
    if overlap_words <= 0:
        return [], 0
    kept: list[str] = []
    length = 0
    for paragraph in reversed(buffer):
        if length >= overlap_words:
            break
        kept.insert(0, paragraph)
        length += len(paragraph.split())
    return kept, length


def _merged_pages(buffer: list[Chapter]) -> list[int] | None:
    """The page span a merged chapter covers, first page to last.

    Consolidation is exactly where page numbers earn their keep and exactly
    where they would otherwise be lost: the books that need merging are the
    page-sized ones, so a real case is 160 one-page PDF fragments becoming 18
    chapters, or 285 scanned epub pages becoming 36. Dropping the numbers here
    would leave those books - the ones with no usable chapter titles - with no
    locator at all."""
    spans = [c.pages for c in buffer if c.pages]
    if not spans:
        return None
    return [min(s[0] for s in spans), max(s[-1] for s in spans)]
