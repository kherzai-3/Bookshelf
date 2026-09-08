from bookrag.ingest.chapter import Chapter
from bookrag.ingest.consolidate import (
    CONSOLIDATION_MEDIAN_WORDS_THRESHOLD,
    consolidate_fragments,
    should_consolidate,
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
