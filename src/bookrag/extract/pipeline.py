"""Runs a provider over every chapter of a book, in order, resolving
entities and appending facts - the actual extraction pipeline."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bookrag.extract.resolve import (
    load_entities,
    prune_book_from_entities,
    resolve_entity,
    save_entities,
    seed_alias_group,
)
from bookrag.providers.base import ExtractionParseError, Provider, extraction_identity
from bookrag.storage import (
    library_root,
    load_chapters,
    load_declared_aliases,
    load_metadata,
    series_reading_order,
)

OnChapterDone = Callable[[int, int], None]


class ExtractionResumeMismatch(Exception):
    """Raised when a resumed run would append a different provider/model's
    facts onto the ones already in facts.jsonl.

    extract_book's contract has always been "the same book, the same
    provider/model, continuing an interrupted run" - this makes it true
    rather than merely documented. A book whose chapters 0-30 were extracted
    by one model and 31-75 by another is not a library with a footnote; it's
    a library whose facts silently disagree about a character for reasons no
    reader can see, and nothing downstream records which model wrote which
    line. The refusal is deliberately loud and non-recoverable: the two ways
    out (re-run with the original model, or --restart and pay for a full
    fresh run) are both the caller's decision to make, not a default this
    can pick for them.
    """

    def __init__(self, recorded: str, current: str, next_chapter_index: int) -> None:
        super().__init__(
            f"This book's facts were extracted with {recorded}, but this run uses {current}. "
            f"Resuming would append one model's facts to another's, from chapter {next_chapter_index} on. "
            f"Re-run with {recorded}, or pass --restart to discard the existing facts and start over."
        )
        self.recorded = recorded
        self.current = current
        self.next_chapter_index = next_chapter_index


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

# Entity types whose names *can* be proper nouns, and so may be required to
# appear in the chapter capitalized. Themes and concepts are deliberately
# excluded: a model routinely title-cases them ("Courage", "Anchoring") where
# the prose only ever says "courage", so demanding the capitalized form there
# would reject perfectly good facts.
_PROPER_NOUN_ENTITY_TYPES = {"character", "setting"}

# Words that may appear lowercase inside an otherwise capitalized name
# ("The Ruins of Gorlan") without making it a common-noun description.
_NAME_CONNECTORS = {"of", "the", "a", "an", "and", "de", "du", "di", "la", "le", "van", "von"}


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


def recorded_extraction_identity(book_id: str, root: Path | None = None) -> str | None:
    """The provider+model string saved with this book's extraction progress,
    or None for a book extracted before this was recorded (or never
    extracted at all). Same read-only, tolerant posture as
    resume_start_index: an unreadable or absent file is "unknown", not an
    error - the caller decides what unknown means."""
    root = root or library_root()
    progress_path = root / book_id / "extraction_progress.json"
    if not progress_path.exists():
        return None
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    identity = progress.get("provider")
    return str(identity) if identity else None


def resume_blocker(
    book_id: str, provider: Provider, root: Path | None = None, *, start_index: int
) -> ExtractionResumeMismatch | None:
    """The mismatch extract_book would raise for this (book, provider), or
    None if resuming is fine. Returned rather than raised so cli.py can ask
    the question *before* announcing "Resuming from chapter N" and starting a
    run that would immediately refuse - one source of truth for the policy,
    two call sites with different needs.

    Either identity being None means unverifiable, not mismatched: a book
    extracted before this was recorded, or a provider that doesn't identify
    itself, must still be resumable.
    """
    if start_index <= 0:
        return None
    recorded_identity = recorded_extraction_identity(book_id, root)
    current_identity = extraction_identity(provider)
    if recorded_identity and current_identity and recorded_identity != current_identity:
        return ExtractionResumeMismatch(recorded_identity, current_identity, start_index)
    return None


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

    # Deliberately after the already-complete short-circuit above: a finished
    # book writes nothing, so there is nothing there to corrupt, and
    # "already complete, pass --restart" is the more useful thing to say.
    blocker = resume_blocker(book_id, provider, root, start_index=start_index)
    if blocker is not None:
        raise blocker
    current_identity = extraction_identity(provider)

    entities = load_entities(root)
    # A restart truncates facts.jsonl (file_mode "w" below), so every entity
    # the discarded run resolved has to go with it - otherwise it survives
    # with nothing behind it: still seeded into known_names, still claiming
    # this book in book_ids, still counted by `bookrag show`. Real observed
    # consequence: an entity left claiming a book that held zero facts about
    # it, which then looked exactly like a genuine cross-book merge.
    # prune_book_from_entities only strips THIS book_id, so an entity an
    # earlier series book also owns keeps that book and survives - correct,
    # since that run's facts were not discarded.
    if restart:
        pruned, _ = prune_book_from_entities(entities, book_id)
        if pruned:
            save_entities(entities, root)

    # Re-applied on every run, not just the first, and deliberately *after*
    # the restart prune above. A declared alias set is a statement about the
    # book, not a product of one extraction, and the prune cannot tell a
    # seeded entity from one the discarded run created - so without this a
    # `--restart` silently un-links the character. Confirmed before it
    # existed: a linked Conn/Connwaer came back as two entities with no
    # aliases. seed_alias_group is idempotent, so a normal resumed run
    # re-applies the same groups and changes nothing.
    declared = load_declared_aliases(book_id, root)
    if declared:
        for group in declared:
            seed_alias_group(entities, book_id, group["names"], epithets=group["epithets"])
        save_entities(entities, root)

    entities_before = len(entities["entities"])
    # .get(..., "fiction"): a book ingested before content_type existed has
    # no such key in its metadata.json - defaults to the taxonomy every book
    # used before this was introduced.
    content_type = load_metadata(book_id, root).get("content_type", "fiction")

    # Includes book_id itself (not just earlier series books) so a resumed
    # run knows about every entity this book has already resolved so far -
    # otherwise the grounding check below would wrongly treat an
    # already-established entity as brand new the moment a run resumes.
    # One lookup, three uses: the two known-* seeds below and, newly, the
    # identity scope handed to resolve_entity per fact. All three have to be
    # the same set of books or the pipeline contradicts itself - telling the
    # provider a name is already known while resolving it to a fresh entity.
    reading_order = series_reading_order(book_id, root)
    known_names = _entity_names_for_books(reading_order, entities)
    known_types = _entity_types_for_books(reading_order, entities)
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
                        raw_facts = provider.extract_facts(chapter.text, known_names, content_type, known_types)
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
                    # about the protagonist to a name ("Arthur Penhaligon")
                    # that never occurs anywhere in that chapter, from an
                    # entirely different book series. This only gates NEW
                    # entities - a fact about an already-known one is fine
                    # even if this chapter only refers to them by pronoun.
                    if is_new and not _entity_is_grounded(raw.entity_name, raw.entity_type, chapter.text):
                        ungrounded_entity_count += 1
                        continue

                    entity_id = resolve_entity(
                        raw.entity_name, raw.entity_type, book_id, entities, scope=reading_order
                    )
                    if is_new:
                        known_names.append(raw.entity_name)
                        known_types[raw.entity_name] = raw.entity_type
                    record = {
                        "entity_id": entity_id,
                        # The name the model actually returned, before
                        # resolution. Without it a merge is permanent: the
                        # record says which entity owns a fact and nothing
                        # says which surface form it arrived as, so two
                        # characters wrongly combined - by a bad alias link or
                        # a bad doctor merge - cannot be told apart again, let
                        # alone separated. With it, a wrong merge is a
                        # reportable, undoable state rather than silent
                        # corruption. Costs one short field per fact and no
                        # model work, since resolution already had this in
                        # hand. Absent on every record written before this
                        # existed, so readers must treat it as optional.
                        "entity_name": raw.entity_name,
                        "chapter_index": chapter.index,
                        "category": raw.category,
                        "statement": raw.statement,
                        # Story-time position, distinct from chapter_index
                        # (which is discourse position and alone governs
                        # spoiler safety). time_phrase is omitted rather than
                        # written as null when absent, which is the common
                        # case - keeps the line short and leaves older
                        # records, which have neither key, indistinguishable
                        # from a new record with nothing to say.
                        "when": raw.when,
                    }
                    if raw.time_phrase:
                        record["time_phrase"] = raw.time_phrase
                    f.write(json.dumps(record) + "\n")
                    fact_count += 1

                # Flush after every chapter, not just on process exit - a
                # long book run (real: 22+ minutes) writes to a redirected
                # file/background log, which Python fully buffers by
                # default. Without this, facts.jsonl and any progress
                # output look frozen even while genuinely making progress.
                f.flush()
                # Saved every chapter, in lockstep with the facts flush above,
                # because the three files have to stay consistent with each
                # other or the library is left corrupt. This used to run only
                # in the `finally` below, which a clean exception path honours
                # but an abrupt kill does not - and that is not hypothetical:
                # a real run killed mid-chapter left 38 facts in facts.jsonl
                # (chapters 4-10) pointing at entity_ids that were never
                # written to entities.json. Those facts are unrecoverable,
                # because a fact record stores only the entity_id and the name
                # lived solely in the registry: some entities were silently
                # re-created under fresh ids later in the same book (the same
                # character split across two ids, half its facts unreachable
                # by name), and others simply render as a raw
                # "character-5049ebd0" forever. Rewriting an ~80KB registry
                # per chapter is nothing next to the minutes of inference each
                # chapter already costs.
                save_entities(entities, root)
                # Written after every chapter (not just at the end) for the
                # same durability reason as the flush above - whatever
                # interrupts this run (Ctrl+C, a dropped connection, a
                # crash), the next call resumes right after the last
                # chapter that actually finished, never re-processing it.
                # Deliberately written LAST: if the process dies between the
                # writes above and this one, the worst case is re-processing
                # one chapter, whose facts are then deduplicated by entity
                # resolution. The reverse order would advance past a chapter
                # whose facts were never persisted.
                progress = {
                    "chapter_count": len(chapters),
                    "next_chapter_index": chapter.index + 1,
                }
                # Omitted rather than written as null when the provider has
                # no identity, so the key's presence always means "this was
                # verified as of the last chapter written". Note this stamps
                # the *current* run's identity even when resuming a file that
                # had none - the earlier chapters' model is unknowable at
                # that point, and recording the half we do know is strictly
                # better than recording nothing.
                if current_identity:
                    progress["provider"] = current_identity
                progress_path.write_text(json.dumps(progress), encoding="utf-8")
                if on_chapter_done is not None:
                    on_chapter_done(position, len(chapters))
    finally:
        # Still here for the clean-exception path (a provider going away
        # mid-chapter), which unwinds before the per-chapter save above runs.
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


def _entity_is_grounded(entity_name: str, entity_type: str, chapter_text: str) -> bool:
    """Whether a brand-new entity's name really occurs in the chapter that
    supposedly introduced it.

    This was a plain case-insensitive substring test, which fails open on
    exactly the names most likely to be hallucinated: a short name that is
    also an ordinary English word. "Will" is a substring of "he will go", so
    a hallucinated "Will" was grounded by 111 of Moby Dick's 147 chapters -
    the guard was effectively off for the very name the extraction prompt's
    own worked example used to be written around (see prompts.py, which no
    longer names any real book's characters). "Halt"/"halt", "May"/"may",
    "Art"/"art" and "Rose"/"rose" all fail the same way.

    Two changes close it. The name must match on word boundaries, so "Art"
    no longer rides in on "start"; and a proper noun must appear capitalized
    as written, not merely as some lowercase word, which is the only thing
    that separates the name "Will" from the verb. The second rule is safe
    because a character or place genuinely introduced in a chapter is
    capitalized there - and it is applied only to the entity types that are
    actually proper nouns.
    """
    name = entity_name.strip()
    if not name:
        return False

    # Singular/plural is not a grounding failure: the chapter that introduces
    # "Waste Person" writes "Waste persons are those...", and "Wargals" is
    # the same entity as "Wargal". Matching the stem with an optional
    # inflection covers both directions. Measured on the real library, a
    # trailing word boundary without this rejected 4 legitimate entities.
    stem = name
    if len(name) > 3 and name.lower().endswith("es"):
        stem = name[:-2]
    elif len(name) > 2 and name.lower().endswith("s"):
        stem = name[:-1]
    pattern = re.escape(stem) + r"(?:e?s)?"

    # `\b` only asserts a boundary next to a word character, so a name that
    # starts with punctuation would never match if anchored blindly.
    if name[0].isalnum() or name[0] == "_":
        pattern = r"\b" + pattern
    if stem[-1:].isalnum() or stem[-1:] == "_":
        pattern = pattern + r"\b"

    flags = re.IGNORECASE
    if entity_type in _PROPER_NOUN_ENTITY_TYPES and _looks_like_a_proper_noun(name):
        flags = 0
    return re.search(pattern, chapter_text, flags) is not None


def _looks_like_a_proper_noun(name: str) -> bool:
    """Whether a name is a real name ("Will", "Castle Araluen") rather than a
    common-noun description a model sometimes files as a character ("Old
    man", "The rowers", "Two intruders").

    Only the former gets the case-sensitive treatment in _entity_is_grounded.
    That keeps the fix aimed squarely at the bug - a name that doubles as an
    everyday word - instead of also dropping the descriptor-style entities,
    which are grounded honestly enough even though the prose keeps them
    lowercase. Measured on the real library, this is the difference between
    14 newly-rejected entities and 0.
    """
    tokens = [t for t in re.split(r"[\s\-']+", name) if t and t[0].isalpha()]
    if not tokens or not tokens[0][0].isupper():
        return False
    return all(t[0].isupper() or t.lower() in _NAME_CONNECTORS for t in tokens)


def _entity_names_for_books(book_ids: list[str], entities: dict) -> list[str]:
    return [
        entity["canonical_name"]
        for entity in entities["entities"]
        if any(bid in entity["book_ids"] for bid in book_ids)
    ]


def _entity_types_for_books(book_ids: list[str], entities: dict) -> dict[str, str]:
    """Name -> established entity_type, for entities already known across
    the given books - passed to the provider so a recurring entity is
    anchored to keep the same type instead of the model re-deriving it from
    scratch each chapter (see resolve_entity's type-scoped matching - a
    name typed differently in different chapters creates separate
    entities). If the same name was inconsistently typed across earlier
    chapters - the exact drift this exists to prevent going forward - the
    last-encountered type wins; a soft hint, not an enforced identity, so
    an arbitrary tie-break here is harmless."""
    types: dict[str, str] = {}
    for entity in entities["entities"]:
        if any(bid in entity["book_ids"] for bid in book_ids):
            types[entity["canonical_name"]] = entity["type"]
    return types
