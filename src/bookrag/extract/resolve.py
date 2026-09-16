"""Resolve a raw extracted entity_name to a canonical entity_id, against the
global entity registry in data/library/entities.json. Matching is
case-insensitive against a canonical name or a known alias, with light
normalization (a leading "the ", a trailing "s") so simple spelling/plural
variants of the same entity_type unify - see match_key. No real fuzzy/
semantic similarity matching or cross-type merging; anything else becomes
a brand new entity.

The registry is one global file, but identity is NOT global: resolve_entity
only ever matches within its `scope` of book_ids (normally a series), so two
unrelated books can each have their own "Michael" without becoming one
person. See resolve_entity's docstring for why the default scope is the
narrow one."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from bookrag.storage import library_root


def entities_path(root: Path | None = None) -> Path:
    return (root or library_root()) / "entities.json"


def load_entities(root: Path | None = None) -> dict:
    path = entities_path(root)
    if not path.exists():
        return {"entities": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_entities(entities: dict, root: Path | None = None) -> None:
    path = entities_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entities, indent=2), encoding="utf-8")


def match_key(name: str) -> str:
    """Normalizes a name for *matching only* - never mutates a stored
    canonical_name/alias, only what resolve_entity compares. Strips a
    leading "the " and a trailing "s" (comparison-only, naive plural
    handling) so "Wargal"/"Wargals"/"The Wargals"/"The Wargal" all produce
    the same key. Deliberately simple rather than a real stemming/fuzzy
    library - covers the real observed duplication case without the
    false-positive risk (two genuinely different names colliding) that a
    more aggressive similarity match would carry, and this only ever
    unifies within the same entity_type (see resolve_entity) - it never
    merges e.g. a "setting" and a "character" that happen to share a
    root name."""
    key = name.strip().lower()
    if key.startswith("the "):
        key = key[4:]
    if key.endswith("s") and len(key) > 1:
        key = key[:-1]
    return key


def looks_like_a_name_variant(first: str, second: str) -> bool:
    """Whether two names plausibly name the same person by spelling alone -
    "Conn" and "Connwaer", or anything `match_key` already unifies.

    **Never sufficient evidence on its own.** Measured across a real
    493-entity library, prefix-shaped pairs were wrong 6 times out of 6
    ("Machine"/"Machinery", "King"/"Kingdom", "Skandia"/"Skandians" - a place
    and its people). Every caller pairs it with something else:
    `library._prefix_shaped_pairs` requires the book to state the link,
    `ingest.vocatives.auto_link_plan` requires both names to read as proper
    nouns addressed to the narrator.

    Single-token only. Across a space this degenerates - every "Baron X" would
    match every "Baron Y" - and the multi-token cases have their own rules in
    `library.py`."""
    a, b = first.strip().lower(), second.strip().lower()
    if not a or not b or " " in a or " " in b:
        return False
    if match_key(a) == match_key(b):
        return True
    short, long = sorted([a, b], key=len)
    return len(short) >= 3 and short != long and long.startswith(short)


def resolve_entity(
    name: str, entity_type: str, book_id: str, entities: dict, scope: list[str] | None = None
) -> str:
    """Mutates `entities` in place (adds a new entry, or records book_id
    against an existing match) and returns the resolved entity_id.

    `scope` is the set of book_ids allowed to share one identity - normally
    `storage.series_reading_order(book_id)`, so book 2 of a series reuses
    book 1's Halt instead of creating a second one. **It defaults to
    `[book_id]`, i.e. no sharing at all**, because the failure mode of
    guessing wrong is asymmetric: too narrow a scope duplicates an entity
    within a series (visible, and fixable by `bookrag doctor`), while too
    wide a scope silently fuses two unrelated books' characters into one
    record that then misreports which books they appear in. `entities.json`
    is a single global registry, so before this existed the match loop ran
    over every book ever ingested and the wide failure was the default -
    four real merges in a four-book library (two unrelated "character"
    names, two unrelated nonfiction "concept" names).

    Note this does not retroactively split entities already merged that way;
    they need `bookrag doctor` or a re-extraction.
    """
    allowed = set(scope) if scope is not None else {book_id}
    name_key = match_key(name)
    for entity in entities["entities"]:
        if entity["type"] != entity_type:
            continue
        if not allowed.intersection(entity["book_ids"]):
            continue
        # Epithets are matched here and *only* here. This comparison is exact
        # after match_key normalization, so an epithet of "boy" absorbs an
        # entity the model named "boy"/"Boy"/"boys" and can never reach for a
        # different boy. query.select_relevant_facts substring-matches names
        # against a question and deliberately never reads this list - see that
        # file, and this module's context doc, for why the two are not
        # interchangeable.
        if (
            name_key == match_key(entity["canonical_name"])
            or any(name_key == match_key(alias) for alias in entity["aliases"])
            or any(name_key == match_key(epithet) for epithet in entity.get("epithets", []))
        ):
            if book_id not in entity["book_ids"]:
                entity["book_ids"].append(book_id)
            return entity["entity_id"]

    entity_id = f"{entity_type}-{uuid.uuid4().hex[:8]}"
    entities["entities"].append(
        {
            "entity_id": entity_id,
            "canonical_name": name.strip(),
            "type": entity_type,
            "aliases": [],
            "book_ids": [book_id],
        }
    )
    return entity_id


def seed_alias_group(
    entities: dict,
    book_id: str,
    names: list[str],
    entity_type: str = "character",
    epithets: list[str] | None = None,
) -> tuple[str, bool]:
    """Make one entity own every name in `names` for this book, creating it if
    needed. Mutates `entities` in place; returns `(entity_id, created)`.

    This is what makes a declared alias set take effect: `resolve_entity` below
    already matches an incoming name against a known entity's aliases, so an
    entity carrying them *before* extraction runs absorbs every later mention
    and the character is never split in the first place. Verified end to end -
    the same book extracts as two entities unseeded and one seeded.

    Idempotent, because `extract_book` re-applies the book's declared groups on
    every run (a `--restart` prunes the entities the discarded run made, and
    would otherwise take the declaration with it)."""
    cleaned = [name.strip() for name in names if name.strip()]
    if len(cleaned) < 2:
        raise ValueError("seed_alias_group needs at least two names")

    keys = {match_key(name) for name in cleaned}
    existing = next(
        (
            entity
            for entity in entities["entities"]
            if entity["type"] == entity_type
            and book_id in entity["book_ids"]
            and (
                match_key(entity["canonical_name"]) in keys
                or any(match_key(alias) in keys for alias in entity["aliases"])
            )
        ),
        None,
    )

    created = existing is None
    if existing is None:
        existing = {
            "entity_id": f"{entity_type}-{uuid.uuid4().hex[:8]}",
            "canonical_name": cleaned[0],
            "type": entity_type,
            "aliases": [],
            "book_ids": [book_id],
        }
        entities["entities"].append(existing)

    for name in cleaned:
        if match_key(name) == match_key(existing["canonical_name"]):
            continue
        if not any(match_key(alias) == match_key(name) for alias in existing["aliases"]):
            existing["aliases"].append(name)

    # Kept in their own list, never folded into `aliases`. The split is the
    # whole safety property: both reach resolve_entity, only `aliases` reaches
    # question matching.
    if epithets:
        known = existing.setdefault("epithets", [])
        for epithet in epithets:
            word = epithet.strip()
            if not word or match_key(word) == match_key(existing["canonical_name"]):
                continue
            if any(match_key(word) == match_key(seen) for seen in [*known, *existing["aliases"]]):
                continue
            known.append(word)
    return existing["entity_id"], created


def prune_book_from_entities(entities: dict, book_id: str) -> tuple[int, int]:
    """Removes book_id from every entity's book_ids (mutates entities in
    place), dropping any entity whose book_ids becomes empty as a result -
    nothing else could ever reference it again once its only book is gone.
    Returns (entities_pruned, entities_deleted). Used by library.remove_book
    and bookrag doctor's orphaned-entity cleanup."""
    pruned = 0
    kept = []
    for entity in entities["entities"]:
        if book_id in entity["book_ids"]:
            entity["book_ids"].remove(book_id)
            pruned += 1
        if entity["book_ids"]:
            kept.append(entity)
    deleted = len(entities["entities"]) - len(kept)
    entities["entities"] = kept
    return pruned, deleted
