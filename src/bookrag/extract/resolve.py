"""Resolve a raw extracted entity_name to a canonical entity_id, against the
global entity registry in data/library/entities.json. Matching is
case-insensitive against a canonical name or a known alias, with light
normalization (a leading "the ", a trailing "s") so simple spelling/plural
variants of the same entity_type unify - see _match_key. No real fuzzy/
semantic similarity matching or cross-type merging; anything else becomes
a brand new entity."""

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


def _match_key(name: str) -> str:
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


def resolve_entity(name: str, entity_type: str, book_id: str, entities: dict) -> str:
    """Mutates `entities` in place (adds a new entry, or records book_id
    against an existing match) and returns the resolved entity_id."""
    name_key = _match_key(name)
    for entity in entities["entities"]:
        if entity["type"] != entity_type:
            continue
        if name_key == _match_key(entity["canonical_name"]) or any(
            name_key == _match_key(alias) for alias in entity["aliases"]
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
