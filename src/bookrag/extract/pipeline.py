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
    duplicate_fact_count: int = 0
    # Both new: added for resumable extraction. resumed_from_chapter is the
    # chapter index this call started at (None for a fresh/from-scratch
    # run); already_complete means this call did nothing because a prior
    # run already finished every chapter (see extraction_progress.json below).
    resumed_from_chapter: int | None = None
    already_complete: bool = False


def resume_start_index(
    book_id: str, root: Path | None = None, *, restart: bool = False, chapter_count: int | None = None
) -> int:
    """Reads extraction_progress.json (if any) and returns the chapter index
    a call to extract_book would start at - 0 for a fresh/restarted run or a
    book with no saved progress, chapter_count if already fully extracted.
    Read-only and cheap (no facts.jsonl/entities.json access) - factored out
    of extract_book so cli.py can preview this before running anything, e.g.
    to print "Resuming from chapter N" before the run actually starts."""
    root = root or library_root()
    if restart:
        return 0
    if chapter_count is None:
        chapter_count = len(load_chapters(book_id, root))

    progress_path = root / book_id / "extraction_progress.json"
    if not progress_path.exists():
        return 0
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    # A chapter_count mismatch means the book was re-ingested since this
    # progress was recorded (different chapter boundaries/consolidation) -
    # the old chapter indices no longer mean the same thing, so treat it as
    # stale and start fresh rather than resuming into the wrong chapters.
    if progress.get("chapter_count") != chapter_count:
        return 0
    return min(max(int(progress.get("next_chapter_index", 0)), 0), chapter_count)


def extract_book(
    book_id: str,
    provider: Provider,
    root: Path | None = None,
    on_chapter_done: OnChapterDone | None = None,
    restart: bool = False,
) -> ExtractionResult:
    """Runs `provider` over book_id's chapters, in order, from wherever the
    last call left off. Progress is persisted to extraction_progress.json
    after every chapter (same per-chapter durability as facts.jsonl's flush)
    so that a genuine interruption - Ctrl+C, a dropped connection, a crash -
    can be resumed by simply calling this again with the same book_id,
    rather than losing everything and restarting from chapter 0. This is
    scoped narrowly to "the same book, the same provider/model, continuing
    an interrupted run" - not a general checkpoint/versioning system (e.g.
    running a bigger model later without discarding a smaller model's
    results is a separate, not-yet-designed feature).

    `restart=True` ignores any existing progress/facts and starts over from
    chapter 0, same as this function's behavior before resumability existed.
    """
    root = root or library_root()
    chapters = load_chapters(book_id, root)
    progress_path = root / book_id / "extraction_progress.json"
    start_index = resume_start_index(book_id, root, restart=restart, chapter_count=len(chapters))

    # extraction_progress.json is deliberately never deleted, including on a
    # fully successful run - next_chapter_index == len(chapters) doubles as
    # an "already fully extracted" marker, so re-running this on a
    # completed book is a cheap no-op instead of silently repeating a run
    # that can take hours, unless the caller explicitly passes restart=True.
    if chapters and start_index >= len(chapters):
        return ExtractionResult(
            book_id=book_id,
            chapter_count=len(chapters),
            fact_count=0,
            new_entity_count=0,
            parse_failure_count=0,
            ungrounded_entity_count=0,
            skipped_chapter_count=0,
            already_complete=True,
        )

    entities = load_entities(root)
    entities_before = len(entities["entities"])
    # .get(..., "fiction"): a book ingested before content_type existed has
    # no such key in its metadata.json - defaults to the taxonomy every book
    # used before this was introduced.
    content_type = load_metadata(book_id, root).get("content_type", "fiction")

    # Includes book_id itself (not just earlier series books) so a resumed
    # run knows about every entity this book has already resolved so far -
    # otherwise the grounding check below would wrongly treat an
    # already-established entity as brand new the moment a run resumes.
    known_names = _entity_names_for_books(series_reading_order(book_id, root), entities)
    resumed_from_chapter = start_index if start_index > 0 else None

    fact_count = 0
    parse_failure_count = 0
    ungrounded_entity_count = 0
    skipped_chapter_count = 0
    duplicate_fact_count = 0
    facts_path = root / book_id / "facts.jsonl"
    file_mode = "a" if start_index > 0 else "w"
    try:
        with facts_path.open(file_mode, encoding="utf-8") as f:
            for position, chapter in enumerate(chapters[start_index:], start=start_index + 1):
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

                # A small local model asked to fill a generous maxItems
                # budget sometimes pads it by repeating a fact it already
                # reported (real, observed: the same status sentence
                # verbatim 20+ times in one chapter) rather than stopping
                # once it runs out of genuinely distinct content - an
                # explicit "don't repeat yourself" prompt instruction did
                # not reliably stop this, so it's caught here instead,
                # code-side, not left to the model's own compliance.
                # Case-insensitive on (entity_name, statement) - exact
                # repeats only, never a near-duplicate rephrasing, which
                # could legitimately be two distinct observations.
                deduped_facts = []
                seen_this_chapter = set()
                for raw in raw_facts:
                    key = (raw.entity_name.strip().lower(), raw.statement.strip().lower())
                    if key in seen_this_chapter:
                        duplicate_fact_count += 1
                        continue
                    seen_this_chapter.add(key)
                    deduped_facts.append(raw)
                raw_facts = deduped_facts

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
                # Written after every chapter (not just at the end) for the
                # same durability reason as the flush above - whatever
                # interrupts this run (Ctrl+C, a dropped connection, a
                # crash), the next call resumes right after the last
                # chapter that actually finished, never re-processing it.
                progress_path.write_text(
                    json.dumps({"chapter_count": len(chapters), "next_chapter_index": chapter.index + 1}),
                    encoding="utf-8",
                )
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
        duplicate_fact_count=duplicate_fact_count,
        resumed_from_chapter=resumed_from_chapter,
    )


def _entity_names_for_books(book_ids: list[str], entities: dict) -> list[str]:
    return [
        entity["canonical_name"]
        for entity in entities["entities"]
        if any(bid in entity["book_ids"] for bid in book_ids)
    ]
