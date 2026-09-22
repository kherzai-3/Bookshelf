"""Turn a fact into a place a reader can actually go and look.

A fact carries `(book_id, chapter_index)` and nothing else. That is enough to
*store* it and not nearly enough to cite it: "chapter 34" is unfindable in a
five-book stitched epub, meaningless in a page-scanned book whose "chapters"
this project invented by merging fragments, and unhelpful even at its best,
because a chapter is two to three thousand words.

**The deliverable is a rendered location, not a storage layout.** What the
database keys a chapter as is irrelevant; what matters is that the reader is
told something they can act on. So this module answers one question - where
did this come from, said in the reader's terms - and it answers it from
whatever evidence the book actually has.

## The quote is the primary locator

Every structural label here is edition-dependent: a page number belongs to one
scan, a chapter number belongs to one printing. **A sentence belongs to the
book.** A reader can search for it in any reader, any edition, any format, and
land exactly on the passage. So `cite()` leads with the structural label for
orientation and carries the matched sentence as the thing that actually finds
it. When the two disagree - a scanned page number a few pages off the printed
folio - the quote is what rescues the citation.

This is also why the passage matcher is allowed to fail. Returning no quote
costs a citation some precision; returning the *wrong* quote sends a reader to
a passage that does not say what they were told it says, which is worse than
saying nothing. `_MIN_PASSAGE_SCORE` is set accordingly.

## What each book in the corpus can offer

Measured after `epub_loader` was taught to read the table of contents and both
loaders to record pages. Before that, three of eight books had no usable
locator at all:

    book                    titled     heading-like   paged
    Moby Dick               147/147    136/147        -
    The Perfect Run         132/132    130/132        -
    Reverend Insanity      2360/2360  2334/2360       -
    Magic Thief              83/84      76/84         -      (was 64/84)
    Ranger's Apprentice      75/75      67/75         -      (was 1/75)
    Eye of the World         54/108     53/108        -      (was 0/108)
    Atomic Habits             0/36        0/36      36/36
    Finite & Infinite        18/18        0/18      18/18

The last two are the cases that justify the whole ladder. *Atomic Habits* has
no headings and an empty table of contents, so its only locator is the page
number encoded in its spine filenames. *Finite and Infinite Games* has a title
for every chapter and all of them are meaningless PDF bookmark IDs
("FAIG0080"), so a title-only citation would look informative and be useless -
its page range is the real answer. Eye of the World's 54 unnamed chapters are
the 46-byte separator fragments between real ones.

## Spoiler safety

This is a new render surface, which `tests/test_spoiler_safety.py` says is a
surface with no gate until the gate is pointed at it. Two rules keep it safe,
and both are structural rather than careful:

- A citation reads **only the chapter the fact belongs to**. Callers only ever
  cite facts that already passed `facts_as_of`, so that chapter is one the
  reader has read.
- **Nothing here is derived from the whole book.** No "chapter 12 of 75", no
  "40% through the book", no page count. Those are exactly the shape of leak
  the truncated-library equivalence test exists to catch - a number computed
  over the full library that changes when later chapters are removed. The
  percentage this module does render is a position *within one chapter*, which
  is computed from that chapter's text alone and is identical either way.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from bookrag.storage import library_root

# Words that carry no identifying information, so matching on them is noise.
# Deliberately short: a long stoplist starts removing words that distinguish
# one passage from another, and the IDF weighting below already discounts
# anything common within the chapter - which is the better mechanism, because
# it adapts to the book instead of to English in general.
_STOPWORDS = frozenset(
    """a an the and or but if then than that this these those of to in on at by for with from
    as is are was were be been being am do does did done has have had having it its he she they
    them his her their him not no nor so such very can could will would shall should may might
    must about into over under after before while when where who whom which what there here""".split()
)

_WORD = re.compile(r"[A-Za-z0-9']+")

# A token is kept despite being a stopword when it is capitalized somewhere it
# is not merely sentence-initial - which is the one signal that separates the
# name "Will" from the verb, and the same rule `pipeline._entity_is_grounded`
# already relies on for the same reason.
#
# **Measured, not assumed.** Before this, the highest-scoring match in the
# whole sample was wrong: "Will had not had a 'growing spurt' before Choosing
# Day" scored a perfect 1.00 against a sentence about tomorrow being the
# biggest day of his life, because the protagonist's name was being discarded
# as a modal verb and only "choosing" and "day" were left to match on.
_SENTENCE_END = frozenset(".!?\"'”’")

# A sentence end, or a paragraph break. Paragraph breaks matter because a
# chapter's text is joined with blank lines and dialogue often has no
# terminating punctuation before one.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\"'”’])\s+|\n{2,}")

# Below this weighted-recall score, the best sentence is reported as no match
# rather than as a guess. A wrong quote is worse than no quote: it sends the
# reader to a passage that does not support what they were told, which reads
# as the tool being wrong about the book rather than about the location.
#
# **Measured on real extractor output**, not reasoned about: 49 statements
# from two Ranger's Apprentice chapters, extracted by the real default model
# and hand-scored. At 0.40, 40 of 49 got a quote and 39 of those 40 were
# correct - 97.5% precision at 82% coverage. The nine abstentions still get a
# structural citation, which is the designed degradation.
#
# **The threshold is insensitive where it matters**: 0.30 and 0.40 both match
# 40 of 49, so the exact value is not load-bearing. 0.50 would drop to 37,
# removing the single wrong match (which scored 0.49) at the cost of two
# correct ones. That trade is within noise at this sample size and on one
# book - and one of the two chapters was unusually quotation-heavy dialogue,
# which flatters the scores. Worth revisiting against a wider fact library
# before moving; it is a scoring job, not a code change.
_MIN_PASSAGE_SCORE = 0.40

# A quote long enough to be unique and short enough to read. Real sentences
# run past this often enough to need trimming, and a trimmed quote is still
# searchable as long as the head is intact.
_MAX_QUOTE_CHARS = 220


@dataclass(frozen=True)
class Passage:
    """Where in a chapter a statement came from."""

    quote: str
    start: int  # character offset into the chapter's text
    score: float

    def position_in_chapter(self, chapter_text: str) -> float | None:
        """0.0-1.0 through this chapter. Safe to render: computed from one
        chapter's own text, so it does not change when later chapters are
        removed from the library."""
        if not chapter_text:
            return None
        return min(1.0, max(0.0, self.start / len(chapter_text)))


@dataclass(frozen=True)
class Citation:
    """A rendered location, plus the parts it was built from."""

    book_title: str
    volume: str | None
    chapter_index: int
    chapter_title: str | None
    pages: list[int] | None
    passage: Passage | None
    position: float | None

    def where(self) -> str:
        """The structural half - which book, and where in it."""
        parts = [self.volume or self.book_title]
        if self.pages:
            first, last = self.pages[0], self.pages[-1]
            parts.append(f"p. {first}" if first == last else f"pp. {first}-{last}")
        # A meaningless title is worse than none: "FAIG0080" looks like
        # information and is not. When a book's own pagination is available,
        # that is the better label and the title is dropped.
        elif self.chapter_title:
            parts.append(self.chapter_title)
        else:
            parts.append(f"chapter {self.chapter_index}")
        if self.position is not None and self.pages is None:
            parts.append(f"{round(self.position * 100)}% in")
        return ", ".join(parts)

    def render(self) -> str:
        """The full citation: where it is, and the sentence to search for."""
        where = self.where()
        if self.passage is None:
            return where
        return f'{where} - "{self.passage.quote}"'


def cite(
    book_id: str,
    chapter_index: int,
    statement: str,
    root: Path | None = None,
) -> Citation | None:
    """Where `statement` came from, as a reader would describe it.

    Returns None only when the book or chapter cannot be read at all -
    a book with no titles, no pages and no matchable passage still gets a
    citation, because "chapter 12" is a worse answer than nothing only when
    something better exists.
    """
    root = root or library_root()
    metadata = _read_json(root / book_id / "metadata.json")
    if metadata is None:
        return None
    chapter = _read_chapter(root / book_id / "chapters.jsonl", chapter_index)
    if chapter is None:
        return None
    return _build(metadata, chapter, book_id, chapter_index, statement)


def _build(metadata: dict, chapter: dict, book_id: str, chapter_index: int, statement: str) -> Citation:
    text = chapter.get("text", "")
    passage = find_passage(statement, text)
    return Citation(
        book_title=metadata.get("title") or book_id,
        # A split omnibus volume already *is* its own book, with its own
        # title, so `where()` names it and never names the file it came out
        # of - "The Burning Bridge, Chapter Fourteen" is the citation a reader
        # can use; "Ranger's Apprentice 1 & 2 Bindup" is the thing they were
        # trying to get away from.
        volume=metadata.get("title") if metadata.get("omnibus") else None,
        chapter_index=chapter_index,
        chapter_title=chapter.get("title"),
        pages=chapter.get("pages"),
        passage=passage,
        position=passage.position_in_chapter(text) if passage else None,
    )


def cite_facts(facts, root: Path | None = None) -> list[tuple[object, Citation]]:
    """Cite a whole answer's worth of facts, reading each chapter once.

    Grouped rather than looped because the naive version re-reads a chapter
    per fact, and a single answer routinely draws a dozen facts from the same
    chapter of a 12 MB `chapters.jsonl`. Order is preserved so the caller can
    render sources in the order the facts were given to the model.

    Facts whose book or chapter cannot be read are dropped rather than
    rendered as a partial citation - a source line that cannot say where it
    points is not worth a line.
    """
    root = root or library_root()
    by_chapter: dict[tuple[str, int], list] = {}
    for fact in facts:
        by_chapter.setdefault((fact.book_id, fact.chapter_index), []).append(fact)

    cited: dict[int, Citation] = {}
    for (book_id, chapter_index), group in by_chapter.items():
        metadata = _read_json(root / book_id / "metadata.json")
        chapter = _read_chapter(root / book_id / "chapters.jsonl", chapter_index)
        if metadata is None or chapter is None:
            continue
        for fact in group:
            cited[id(fact)] = _build(metadata, chapter, book_id, chapter_index, fact.statement)
    return [(fact, cited[id(fact)]) for fact in facts if id(fact) in cited]


def find_passage(statement: str, chapter_text: str) -> Passage | None:
    """The sentence in `chapter_text` a fact's statement most likely came from.

    A statement is a model's paraphrase, not a quotation - `extract_book`
    stores what the model returned and nothing anchors it to the source. So
    this is a retrieval problem over one chapter, and the scoring reflects
    what actually distinguishes one passage from another in prose:

    - **Weighted recall of the statement's words**, not similarity. The
      statement is short and the sentence may be long; penalising a sentence
      for containing words the statement omitted would prefer terse sentences
      over the right one.
    - **IDF over the chapter's own sentences**, so a name that appears once
      outweighs a word the chapter uses constantly. This adapts per book: in a
      chapter about Halt, "Halt" is not evidence, and the IDF says so without
      anyone maintaining a list.
    - **Sentence pairs as well as single sentences**, because a paraphrase
      routinely spans a sentence boundary ("He drew his bow. The arrow took
      the boar in the shoulder." -> one fact). Pairs are scored with a small
      penalty so a single sentence wins a tie - the tighter locator is the
      more useful one.
    """
    if not chapter_text.strip():
        return None
    names = names_in(chapter_text)
    wanted = _content_words(statement, names)
    if not wanted:
        return None

    spans = _sentence_spans(chapter_text)
    if not spans:
        return None
    tokenized = [(start, end, _content_words(chapter_text[start:end], names)) for start, end in spans]
    idf = _idf([words for _s, _e, words in tokenized])

    total = sum(idf.get(word, _UNSEEN_IDF) for word in wanted)
    if total <= 0:
        return None

    best: Passage | None = None
    for i, (start, end, words) in enumerate(tokenized):
        for penalty, span_end, span_words in _candidates(tokenized, i, end, words):
            shared = wanted & span_words
            if not shared:
                continue
            score = sum(idf.get(word, _UNSEEN_IDF) for word in shared) / total * penalty
            if best is None or score > best.score:
                best = Passage(quote=_trim(chapter_text[start:span_end]), start=start, score=score)

    if best is None or best.score < _MIN_PASSAGE_SCORE:
        return None
    return best


# A word the chapter never uses. It cannot be matched, but it must still
# count *against* the match, which is why it weighs as much as the rarest word
# the chapter has (IDF here is 1/count, so 1.0 is the maximum).
#
# **The first version scored it 0, and that was the other half of the wrong
# 1.00 match.** Dropping unseen words from the denominator as well as the
# numerator means a statement is scored only on the words it happens to share
# with the book - so "Baron Arald was the Lord of Redmont Fief and had raised
# the castle wards" matched a sentence containing none of Arald, Lord, Redmont
# or Fief at 0.95, because those four were discarded and "castle wards" was
# left to carry the whole score. Unseen words are the strongest available
# evidence that a passage is *not* the source; scoring them as nothing inverted
# that.
_UNSEEN_IDF = 1.0

# A two-sentence match must beat a one-sentence match by this much to win.
_PAIR_PENALTY = 0.95


def _candidates(tokenized, i, end, words):
    yield 1.0, end, words
    if i + 1 < len(tokenized):
        _next_start, next_end, next_words = tokenized[i + 1]
        yield _PAIR_PENALTY, next_end, words | next_words


def _idf(documents: list[set[str]]) -> dict[str, float]:
    """Inverse document frequency over the chapter's sentences.

    `log` is deliberately absent: with a few hundred short sentences the
    counts are small and the plain reciprocal separates a once-seen name from
    a dozen-times-seen verb more sharply than a log would, which is the
    separation that matters here.
    """
    counts: dict[str, int] = {}
    for words in documents:
        for word in words:
            counts[word] = counts.get(word, 0) + 1
    return {word: 1.0 / count for word, count in counts.items()}


def _content_words(text: str, names: frozenset[str] = frozenset()) -> set[str]:
    """The words worth matching on. `names` are stopwords this book uses as
    proper nouns, learned from the chapter by `names_in`."""
    words: set[str] = set()
    for match in _WORD.finditer(text):
        word = match.group().lower()
        if len(word) < 2:
            continue
        if word in _STOPWORDS and word not in names:
            continue
        words.add(word)
    return words


def names_in(text: str) -> frozenset[str]:
    """Stopwords this passage uses as proper nouns - "Will" the character
    rather than "will" the modal verb.

    **Learned from the chapter, and then applied to the statement**, which is
    the only ordering that works. Capitalization is the evidence, and a
    statement hands over almost none of it: an extractor writes "Will was
    small and wiry", putting the name in the one position where a capital is
    free. The chapter says the same name a dozen times mid-sentence, so the
    book can answer a question the statement cannot.

    This is the same reading-the-book's-own-prose move the rest of the
    project makes - `names.person_link_groups`, `pipeline._entity_is_grounded`
    - and it is here for the same reason: the alternative is a wordlist that
    is wrong for the next book.
    """
    found: set[str] = set()
    for match in _WORD.finditer(text):
        raw = match.group()
        word = raw.lower()
        if word not in _STOPWORDS or not raw[:1].isupper():
            continue
        before = text[: match.start()].rstrip()
        # Sentence-initial capitalization is grammatical, not evidence.
        if before and before[-1] not in _SENTENCE_END:
            found.add(word)
    return frozenset(found)


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_SPLIT.finditer(text):
        end = match.start()
        if text[start:end].strip():
            spans.append((start, end))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _trim(sentence: str) -> str:
    sentence = " ".join(sentence.split())
    if len(sentence) <= _MAX_QUOTE_CHARS:
        return sentence
    # Cut at a word boundary so the head stays searchable verbatim.
    return sentence[:_MAX_QUOTE_CHARS].rsplit(" ", 1)[0] + "..."


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_chapter(path: Path, chapter_index: int) -> dict | None:
    """One chapter, read without holding the rest in memory.

    Reads line by line rather than loading `chapters.jsonl` whole: a citation
    needs one chapter, and the largest book in the corpus is a 12 MB file of
    2,360 of them. It also keeps the spoiler-safety property visible in the
    code - this function cannot return a chapter other than the one asked for.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("index") == chapter_index:
                    return record
    except (OSError, json.JSONDecodeError):
        return None
    return None
