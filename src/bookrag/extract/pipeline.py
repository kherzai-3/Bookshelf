"""Runs a provider over every chapter of a book, in order, resolving
entities and appending facts - the actual extraction pipeline."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bookrag.extract.resolve import load_entities, resolve_entity, save_entities
from bookrag.providers.base import ExtractionParseError, Provider
from bookrag.storage import library_root, load_chapters, load_metadata, series_reading_order

OnChapterDone = Callable[[int, int], None]

# Real chapters run to hundreds/thousands of words (median 1904 in a real
# book measured); a "chapter" fragment this short is never actual narrative
# content - it's front/back matter (a copyright block, a one-line
# dedication, etc). Real observed cases a small local model hallucinated
# facts for instead of recognizing as non-narrative: a 2-word fragment, a
# ~9-word copyright address block, a ~5-word dedication. Skipping the
# provider call entirely for these is cheap, deterministic, and doesn't
# depend on the model recognizing non-narrative content on its own (the
# extraction prompt also asks for this - see prompts.py - but a longer
# non-narrative fragment, e.g. a table of contents or author bio, can be too
# long for this floor to catch, which is why both defenses exist).
MIN_NARRATIVE_WORDS = 20


@dataclass
class ExtractionResult:
    book_id: str
    chapter_count: int
    fact_count: int
    new_entity_count: int
    parse_failure_count: int
    ungrounded_entity_count: int
    skipped_chapter_count: int


def extract_book(
    book_id: str,
    provider: Provider,
    root: Path | None = None,
    on_chapter_done: OnChapterDone | None = None,
) -> ExtractionResult:
    root = root or library_root()
    chapters = load_chapters(book_id, root)
    entities = load_entities(root)
    entities_before = len(entities["entities"])
    # .get(..., "fiction"): a book ingested before content_type existed has
    # no such key in its metadata.json - defaults to the taxonomy every book
    # used before this was introduced.
    content_type = load_metadata(book_id, root).get("content_type", "fiction")

    prior_book_ids = series_reading_order(book_id, root)[:-1]
    known_names = _entity_names_for_books(prior_book_ids, entities)

    fact_count = 0
    parse_failure_count = 0
    ungrounded_entity_count = 0
    skipped_chapter_count = 0
    facts_path = root / book_id / "facts.jsonl"
    try:
        with facts_path.open("w", encoding="utf-8") as f:
            for position, chapter in enumerate(chapters, start=1):
                if len(chapter.text.split()) < MIN_NARRATIVE_WORDS:
                    skipped_chapter_count += 1
                    raw_facts = []
                else:
                    # A malformed response for one chapter (real, observed: a
                    # tiny dedication-page "chapter" confusing a small local
                    # model) shouldn't abort a whole multi-hour book run - skip
                    # it and keep going. A different failure (e.g. the provider
                    # being unreachable) is NOT caught here and does abort, since
                    # retrying every remaining chapter against a dead provider is
                    # pointless.
                    try:
                        raw_facts = provider.extract_facts(chapter.text, known_names, content_type)
                    except ExtractionParseError:
                        parse_failure_count += 1
                        raw_facts = []

                for raw in raw_facts:
                    is_new = raw.entity_name not in known_names
                    # A *new* entity's name should appear somewhere in the
                    # chapter that supposedly introduced it - real, observed
                    # failure: a small local model attached a real line
                    # about Will to a name ("Arthur Penhaligon") that never
                    # occurs anywhere in that chapter, from an entirely
                    # different book series. This only gates NEW entities -
                    # a fact about an already-known one is fine even if
                    # this chapter only refers to them by pronoun.
                    if is_new and raw.entity_name.lower() not in chapter.text.lower():
                        ungrounded_entity_count += 1
                        continue

                    entity_id = resolve_entity(raw.entity_name, raw.entity_type, book_id, entities)
                    if is_new:
                        known_names.append(raw.entity_name)
                    record = {
                        "entity_id": entity_id,
                        "chapter_index": chapter.index,
                        "category": raw.category,
                        "statement": raw.statement,
                    }
                    f.write(json.dumps(record) + "\n")
                    fact_count += 1

                # Flush after every chapter, not just on process exit - a
                # long book run (real: 22+ minutes) writes to a redirected
                # file/background log, which Python fully buffers by
                # default. Without this, facts.jsonl and any progress
                # output look frozen even while genuinely making progress.
                f.flush()
                if on_chapter_done is not None:
                    on_chapter_done(position, len(chapters))
    finally:
        # Persist whatever entities were resolved even if the loop above
        # aborts partway (a non-ExtractionParseError failure) - partial
        # progress shouldn't silently vanish.
        save_entities(entities, root)

    return ExtractionResult(
        book_id=book_id,
        chapter_count=len(chapters),
        fact_count=fact_count,
        new_entity_count=len(entities["entities"]) - entities_before,
        parse_failure_count=parse_failure_count,
        ungrounded_entity_count=ungrounded_entity_count,
        skipped_chapter_count=skipped_chapter_count,
    )


def _entity_names_for_books(book_ids: list[str], entities: dict) -> list[str]:
    return [
        entity["canonical_name"]
        for entity in entities["entities"]
        if any(bid in entity["book_ids"] for bid in book_ids)
    ]
