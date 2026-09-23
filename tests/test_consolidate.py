from bookrag.ingest.chapter import Chapter
from bookrag.ingest.consolidate import (
    CONSOLIDATION_MEDIAN_WORDS_THRESHOLD,
    CONSOLIDATION_TARGET_WORDS,
    SPLIT_OVERSIZED_CHAPTERS,
    SPLIT_THRESHOLD_WORDS,
    consolidate_fragments,
    should_consolidate,
    split_for_extraction,
)


def _chapter(index: int, word_count: int, title: str | None = None) -> Chapter:
    return Chapter(index=index, title=title, text=" ".join(["word"] * word_count))


def test_should_consolidate_is_true_below_the_median_threshold() -> None:
    chapters = [_chapter(i, 300) for i in range(10)]

    assert should_consolidate(chapters) is True


def test_should_consolidate_is_false_at_or_above_the_median_threshold() -> None:
    chapters = [_chapter(i, CONSOLIDATION_MEDIAN_WORDS_THRESHOLD + 500) for i in range(10)]

    assert should_consolidate(chapters) is False


def test_should_consolidate_is_not_skewed_by_a_few_outliers() -> None:
    """A handful of long front-matter/appendix fragments shouldn't flip the
    decision for a book whose real chapters are all small - median, not
    mean, is the point."""
    chapters = [_chapter(i, 300) for i in range(9)] + [_chapter(9, 20000)]

    assert should_consolidate(chapters) is True


def test_should_consolidate_of_empty_list_is_false() -> None:
    assert should_consolidate([]) is False


def test_consolidate_fragments_merges_up_to_target_words() -> None:
    chapters = [_chapter(i, 700) for i in range(6)]  # 3 pairs of ~1400 words each

    merged = consolidate_fragments(chapters, target_words=1000)

    assert len(merged) == 3
    assert [c.index for c in merged] == [0, 1, 2]
    for chapter in merged:
        assert len(chapter.text.split()) >= 1000


def test_consolidate_fragments_keeps_a_trailing_undersized_remainder() -> None:
    chapters = [_chapter(i, 700) for i in range(5)]  # 2 full pairs + 1 leftover

    merged = consolidate_fragments(chapters, target_words=1000)

    assert len(merged) == 3
    assert len(merged[-1].text.split()) == 700


def test_consolidate_fragments_merges_across_a_titled_fragment() -> None:
    """A title is not a forced boundary - Finite and Infinite Games (PDF)
    gives every fragment a title, but they're meaningless internal bookmark
    IDs, not real chapter breaks. Merging must be driven by word count
    alone regardless of title presence."""
    chapters = [
        _chapter(0, 100),
        _chapter(1, 100),
        _chapter(2, 100, title="Chapter Two"),
        _chapter(3, 100),
    ]

    merged = consolidate_fragments(chapters, target_words=1000)

    assert len(merged) == 1
    assert merged[0].title == "Chapter Two"


def test_consolidate_fragments_keeps_first_title_when_several_are_present() -> None:
    chapters = [
        _chapter(0, 700, title="First"),
        _chapter(1, 700, title="Second"),
    ]

    merged = consolidate_fragments(chapters, target_words=1000)

    assert len(merged) == 1
    assert merged[0].title == "First"


def test_consolidate_fragments_of_empty_list_is_empty() -> None:
    assert consolidate_fragments([]) == []


def test_merging_keeps_the_page_span_it_covers() -> None:
    """Consolidation is exactly where page numbers earn their keep and
    exactly where they would otherwise be lost: the books that need merging
    are the page-sized ones. Real case - 160 one-page PDF fragments become 18
    chapters, and dropping the numbers would leave that book, which has no
    usable titles either, with no locator at all."""
    fragments = [Chapter(index=i, title=None, text="word " * 400, pages=[i + 1, i + 1]) for i in range(6)]

    merged = consolidate_fragments(fragments, target_words=1200)

    assert [c.pages for c in merged] == [[1, 3], [4, 6]]


def test_merging_chapters_without_pages_keeps_none() -> None:
    fragments = [Chapter(index=i, title=None, text="word " * 400) for i in range(4)]

    assert all(c.pages is None for c in consolidate_fragments(fragments, target_words=800))


def test_a_normal_chapter_passes_through_split_untouched() -> None:
    """The overwhelmingly common case, and the one that must be provably
    unaffected: six of the eight books in this project's corpus have no
    chapter anywhere near the threshold."""
    text = "\n".join(f"Paragraph {i} of an ordinary chapter." for i in range(50))

    assert split_for_extraction(text, threshold_words=3500) == [text]


def test_an_oversized_chapter_is_split_into_pieces() -> None:
    text = "\n".join("word " * 100 for _ in range(60))  # 6000 words

    pieces = split_for_extraction(text, threshold_words=3500)

    assert len(pieces) > 1
    assert all(len(p.split()) < 3500 for p in pieces)


def test_split_never_cuts_mid_sentence() -> None:
    """Pieces begin and end on paragraph boundaries, so no piece ever starts
    with half a sentence the model has to guess the front of."""
    paragraphs = [f"Sentence {i} runs to its end here. " * 40 for i in range(40)]
    text = "\n".join(paragraphs)

    pieces = split_for_extraction(text, threshold_words=3500)

    assert len(pieces) > 1
    for piece in pieces:
        for line in piece.splitlines():
            assert line in paragraphs


def test_split_overlaps_pieces_so_a_boundary_paraphrase_survives() -> None:
    """Measured, not assumed: at 800-word pieces, adding a 150-word overlap
    took statements whose quote was lost from 2 to 0."""
    text = "\n".join(f"Paragraph {i} " + "word " * 100 for i in range(60))

    with_overlap = split_for_extraction(text, threshold_words=3500)
    without = split_for_extraction(text, overlap_words=0, threshold_words=3500)

    assert sum(len(p.split()) for p in with_overlap) > sum(len(p.split()) for p in without)
    # The tail of one piece really does reappear at the head of the next.
    assert with_overlap[1].splitlines()[0] in with_overlap[0].splitlines()


def test_split_handles_both_paragraph_separators() -> None:
    """epub_loader joins paragraphs with "\n"; consolidate_fragments joins
    fragments with "\n\n". Splitting on the blank line alone silently
    produces one piece per chapter - it looks clean and does nothing."""
    newline_joined = "\n".join("word " * 100 for _ in range(60))
    blank_line_joined = "\n\n".join("word " * 100 for _ in range(60))

    assert len(split_for_extraction(newline_joined, threshold_words=3500)) > 1
    assert len(split_for_extraction(blank_line_joined, threshold_words=3500)) > 1


def test_an_unbroken_wall_of_text_is_not_split() -> None:
    """No paragraph boundary means no cut that isn't mid-sentence, and a
    mid-sentence cut is worse than a merely large prompt."""
    text = "word " * 6000

    assert split_for_extraction(text, threshold_words=3500) == [text]


def test_split_threshold_sits_above_the_consolidation_target() -> None:
    """These two must not fight: a chapter consolidate_fragments has just
    built up to CONSOLIDATION_TARGET_WORDS must never be immediately taken
    apart again by the splitter."""
    assert SPLIT_THRESHOLD_WORDS > CONSOLIDATION_TARGET_WORDS


def test_splitting_is_off_by_default_whatever_the_chapter_size() -> None:
    """The default path must not split, and the reason is evidence, not
    caution: over six oversized real chapters no decision rule survived (see
    SPLIT_OVERSIZED_CHAPTERS). Turning it on would change 48 of one book's 108
    chapters. This pins the default so it can only be flipped deliberately."""
    huge = "\n".join("word " * 100 for _ in range(200))  # 20,000 words

    assert SPLIT_OVERSIZED_CHAPTERS is False
    assert split_for_extraction(huge) == [huge]
    # ...and the mechanism still works when explicitly asked.
    assert len(split_for_extraction(huge, threshold_words=3500)) > 1
