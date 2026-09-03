"""Spoiler-safe fact retrieval: never return a fact that occurs after the
given (book_id, chapter_index) in series reading order. This is the one
primitive the eventual query/chat layer must go through - every earlier
book in the series counts as fully "in the past"; only the book being
queried is chapter-limited."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bookrag.extract.resolve import load_entities
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


def format_context(facts: list[Fact], root: Path | None = None) -> str:
    """Renders spoiler-safe facts as the plain-text context a provider's
    `answer_question` expects: grouped by entity, then by category, each
    fact tagged with its chapter number and sorted chronologically within
    its group - so a provider (even a small local model) has an explicit
    recency signal to resolve a later chapter superseding an earlier one
    (e.g. a status that changes) without any fact ever being discarded here.
    A coarse "keep only the latest fact per category" rule was considered
    and rejected - status/relationship facts are not single-valued (e.g. a
    character can have several simultaneous status facts), so pruning by
    category alone would silently delete other, still-true facts. Entity
    names are resolved via the global entity registry; an id with no match
    (or no registry at all) falls back to its raw entity_id."""
    if not facts:
        return ""
    names = {e["entity_id"]: e["canonical_name"] for e in load_entities(root)["entities"]}

    by_entity: dict[str, dict[str, list[Fact]]] = {}
    for fact in facts:
        by_entity.setdefault(fact.entity_id, {}).setdefault(fact.category, []).append(fact)

    blocks = []
    for entity_id, by_category in by_entity.items():
        lines = [names.get(entity_id, entity_id)]
        for category, cat_facts in by_category.items():
            lines.append(f"  {category}:")
            lines.extend(
                f"    [ch {f.chapter_index}] {f.statement}"
                for f in sorted(cat_facts, key=lambda fact: fact.chapter_index)
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
