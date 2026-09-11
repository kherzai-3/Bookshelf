"""Spoiler-safe fact retrieval: never return a fact that occurs after the
given (book_id, chapter_index) in series reading order. This is the one
primitive the eventual query/chat layer must go through - every earlier
book in the series counts as fully "in the past"; only the book being
queried is chapter-limited."""

from __future__ import annotations

import difflib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from bookrag.extract.resolve import load_entities, match_key
from bookrag.providers.parsing import OCCURRENCE_CATEGORIES, OCCURRENCE_CATEGORIES_BY_CONTENT_TYPE
from bookrag.storage import library_root, series_reading_order


@dataclass
class Fact:
    book_id: str
    entity_id: str
    chapter_index: int
    category: str
    statement: str


def facts_as_of(book_id: str, chapter_index: int, root: Path | None = None) -> list[Fact]:
    root = root or library_root()
    facts: list[Fact] = []
    for bid in series_reading_order(book_id, root):
        limit = chapter_index if bid == book_id else None
        facts_path = root / bid / "facts.jsonl"
        if not facts_path.exists():
            continue
        for line in facts_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if limit is not None and record["chapter_index"] > limit:
                continue
            facts.append(
                Fact(
                    book_id=bid,
                    entity_id=record["entity_id"],
                    chapter_index=record["chapter_index"],
                    category=record["category"],
                    statement=record["statement"],
                )
            )
    return facts


# Below this ratio, two strings are treated as unrelated rather than a
# likely typo/near-miss of each other - chosen conservatively (favoring
# missed fuzzy matches over false ones) since a false match here only ever
# causes over-inclusion (see select_relevant_facts's no-match fallback),
# never a lost fact.
_FUZZY_MATCH_THRESHOLD = 0.8


def _name_matches_question(name: str, question_lc: str, question_words: list[str]) -> bool:
    name_lc = name.lower()
    if name_lc in question_lc:
        return True
    key = match_key(name)
    # match_key handles the direction plain substring can't: an entity
    # named "The Wargals" isn't a substring of a question asking about
    # "wargal", but its match_key ("wargal") is.
    if key and key in question_lc:
        return True
    # Fuzzy fallback only for single-word names - comparing a whole
    # question word against a multi-word name (e.g. "Random House
    # Australia") via SequenceMatcher would almost never score usefully,
    # and skip anything short enough that near-everything scores high.
    if " " not in name_lc and len(name_lc) >= 3:
        return any(
            difflib.SequenceMatcher(None, word, name_lc).ratio() >= _FUZZY_MATCH_THRESHOLD
            for word in question_words
            if word
        )
    return False


# Function words carry no topical signal, and several of them ("what",
# "happened", "during") open almost every question this tool gets asked - left
# in, they would match nearly every statement and defeat the whole filter.
_STOPWORDS = frozenset(
    """a an the and or but if of in on at to from by for with without about into over under
    is are was were be been being has have had do does did doing will would can could should
    what who whom whose which when where why how that this these those there here it its it's
    he she they them his her their him us we you your i me my mine our ours
    not no nor so than then too very just also only own same s t don now
    tell me more something anything someone anyone happen happened happens happening
    say says said tell tells told know knows knew like likes liked""".split()
)


# Bounds the statement-match path. This is a fallback from "send all 1248
# facts" - which measured 2.1x a real model's context window on a real book -
# so any cap is strictly an improvement, and a generous one still leaves the
# assembled context an order of magnitude inside the window.
_MAX_STATEMENT_MATCHES = 80


def _content_words(text: str) -> set[str]:
    """Lowercased, punctuation-stripped words worth matching on - stopwords and
    very short tokens dropped. Deliberately not stemmed: `match_key` already
    handles the plural case that actually mattered in real data, and a real
    stemmer would be a new dependency for a marginal gain."""
    words = set()
    for raw in text.lower().split():
        word = raw.strip(".,!?;:\"'()[]-—…")
        if len(word) > 2 and word not in _STOPWORDS:
            words.add(word)
    return words


def _facts_matching_question_text(question: str, facts: list[Fact]) -> list[Fact]:
    """Recall net for a question that names no known entity: match the
    question's *distinctive* words against fact statements themselves.

    Rarity is measured across `facts` - the already-spoiler-filtered list -
    and never across the whole book. That is not an optimization: a word's
    rarity computed over chapters the reader hasn't reached is a value derived
    from hidden data, and deriving anything from the unfiltered set is exactly
    how a filter leaks what it removed.

    A word is distinctive if it appears in at most a tenth of the statements,
    so "Kalkara" qualifies and "Ranger" (everywhere in this book) does not.
    Matches are then *scored* by how rare the shared words are and capped,
    rather than gated on a hit count. Requiring two shared words was tried
    first and was wrong on real questions: a reader asking about "the choosing
    ceremony" shares no statement with the book's own phrase, "Choosing Day" -
    only the single word `choosing` - and a hit-count rule discards exactly
    the topic it was supposed to find. Ranking tolerates that mismatch, and
    the cap does the job the hit count was really there for: bounding how much
    reaches the model."""
    if not facts:
        return []
    statement_words = [(fact, _content_words(fact.statement)) for fact in facts]

    document_frequency: Counter[str] = Counter()
    for _, words in statement_words:
        document_frequency.update(words)

    rarity_ceiling = max(1, len(facts) // 10)
    distinctive = {
        word
        for word in _content_words(question)
        if 0 < document_frequency[word] <= rarity_ceiling
    }
    if not distinctive:
        return []

    scored: list[tuple[float, int, Fact]] = []
    for fact, words in statement_words:
        shared = words & distinctive
        if shared:
            # Rarer shared words count for more, so a statement naming the
            # Kalkara outranks one that merely also mentions a castle.
            scored.append((sum(1.0 / document_frequency[word] for word in shared), fact.chapter_index, fact))
    if not scored:
        return []

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [fact for _, _, fact in scored[:_MAX_STATEMENT_MATCHES]]


def select_relevant_facts(question: str, facts: list[Fact], root: Path | None = None) -> list[Fact]:
    """Filters facts down to just the entities a question appears to name,
    so a book with a large fact catalog doesn't unconditionally dump every
    fact about every entity into one answer's context (see
    format_context's own docstring - it deliberately never discards
    anything on its own; this is a separate, question-aware step that runs
    before it, in cli.py's chat loop). Real motivation: a book's assembled
    context can run to tens of thousands of tokens by its later chapters,
    several times the default local model's context window - so this also
    keeps typical context size roughly independent of book length, not
    just book-length-proportional.

    Matching is intentionally cheap and dependency-free, not real
    semantic/embedding search (see README's Future ideas for that): a
    case-insensitive substring check against each candidate entity's
    canonical name and aliases, `extract.resolve.match_key` normalization
    (so a question about "Wargal" matches an entity named "Wargals"/"The
    Wargals"), and a `difflib.SequenceMatcher` fuzzy check as a last
    resort for single-word names. If NO entity in `facts` matches at all -
    a general/topical question naming no specific entity - every fact is
    returned unchanged, the same as if this function didn't exist."""
    if not facts:
        return facts

    entities_by_id = {e["entity_id"]: e for e in load_entities(root)["entities"]}
    question_lc = question.lower()
    question_words = [w.strip(".,!?;:\"'()") for w in question_lc.split()]

    matched_entity_ids: set[str] = set()
    for entity_id in {f.entity_id for f in facts}:
        entity = entities_by_id.get(entity_id)
        candidate_names = [entity["canonical_name"], *entity["aliases"]] if entity else [entity_id]
        if any(_name_matches_question(name, question_lc, question_words) for name in candidate_names):
            matched_entity_ids.add(entity_id)

    if matched_entity_ids:
        return [f for f in facts if f.entity_id in matched_entity_ids]

    # No entity named. Before giving up and returning everything, try matching
    # the question's distinctive words against the statements themselves -
    # real questions like "what happened at the choosing ceremony?" name an
    # event rather than a cataloged entity, and on a real book that fallback
    # was measured at 2.1x the model's context window, i.e. silently truncated.
    by_statement = _facts_matching_question_text(question, facts)
    if by_statement:
        return by_statement

    return facts


def format_context(facts: list[Fact], root: Path | None = None, content_type: str = "fiction") -> str:
    """Renders spoiler-safe facts as the plain-text context a provider's
    `answer_question` expects: grouped by entity, and within an entity split
    into the two kinds of fact that must be READ differently. Every fact is
    tagged with its chapter and sorted chronologically; nothing is ever
    discarded here. A coarse "keep only the latest fact per category" rule
    was considered and rejected - a character can have several simultaneous
    true facts, so pruning by category alone would silently delete still-true
    ones. Entity names resolve via the global entity registry; an id with no
    match (or no registry) falls back to its raw entity_id.

    The split (see `parsing.OCCURRENCE_CATEGORIES`) is the structural half of
    a real bug fix. Occurrences are listed as one chronological sequence with
    their category inline, because they are separate moments that never
    supersede one another - fusing two of them is exactly how a ch.34 wound
    and an unrelated ch.66 death report became "he died fighting the
    monsters." Standing descriptions keep the old per-category grouping,
    because there recency genuinely is the right rule. The headers say so in
    plain language: a small local model follows visible structure far more
    reliably than it follows a paragraph of instructions (the same reason
    this project schema-constrains extraction rather than asking nicely)."""
    if not facts:
        return ""
    names = {e["entity_id"]: e["canonical_name"] for e in load_entities(root)["entities"]}
    occurrence_categories = OCCURRENCE_CATEGORIES_BY_CONTENT_TYPE.get(content_type, OCCURRENCE_CATEGORIES)

    by_entity: dict[str, tuple[list[Fact], dict[str, list[Fact]]]] = {}
    for fact in facts:
        occurrences, attributes = by_entity.setdefault(fact.entity_id, ([], {}))
        if fact.category in occurrence_categories:
            occurrences.append(fact)
        else:
            attributes.setdefault(fact.category, []).append(fact)

    blocks = []
    for entity_id, (occurrences, attributes) in by_entity.items():
        lines = [names.get(entity_id, entity_id)]
        if occurrences:
            lines.append("  What happened, in order - each line is a separate moment, not a correction of the one above:")
            lines.extend(
                f"    [ch {f.chapter_index}] ({f.category}) {f.statement}"
                for f in sorted(occurrences, key=lambda fact: fact.chapter_index)
            )
        if attributes:
            lines.append("  Standing description - a later line refines or supersedes an earlier one:")
            for category, cat_facts in attributes.items():
                lines.append(f"    {category}:")
                lines.extend(
                    f"      [ch {f.chapter_index}] {f.statement}"
                    for f in sorted(cat_facts, key=lambda fact: fact.chapter_index)
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
