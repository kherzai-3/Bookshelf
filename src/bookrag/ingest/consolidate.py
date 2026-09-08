"""Merges many small, incoherent chapter fragments into larger, more
coherent chapters before they're persisted - for a book whose loader
output is real-page-sized (or otherwise too small to extract well from
independently) rather than real-chapter-sized."""

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


def consolidate_fragments(
    chapters: list[Chapter], target_words: int = CONSOLIDATION_TARGET_WORDS
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
    for a genuinely tiny leftover."""
    merged: list[Chapter] = []
    buffer: list[Chapter] = []

    def flush() -> None:
        if not buffer:
            return
        title = next((c.title for c in buffer if c.title), None)
        merged.append(Chapter(index=len(merged), title=title, text="\n\n".join(c.text for c in buffer)))
        buffer.clear()

    for chapter in chapters:
        buffer.append(chapter)
        if sum(len(c.text.split()) for c in buffer) >= target_words:
            flush()
    flush()
    return merged
