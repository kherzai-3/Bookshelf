"""Spoiler-safe fact retrieval: never return a fact that occurs after the
given (book_id, chapter_index) in series reading order. This is the one
primitive the eventual query/chat layer must go through - every earlier
book in the series counts as fully "in the past"; only the book being
queried is chapter-limited."""

from __future__ import annotations

import difflib
import json
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

    if not matched_entity_ids:
        return facts
    return [f for f in facts if f.entity_id in matched_entity_ids]


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
