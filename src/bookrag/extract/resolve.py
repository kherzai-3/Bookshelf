"""Resolve a raw extracted entity_name to a canonical entity_id, against the
global entity registry in data/library/entities.json. No fuzzy/semantic
coreference in v1 - only case-insensitive exact match against a canonical
name or a known alias; anything else becomes a brand new entity."""

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


def resolve_entity(name: str, entity_type: str, book_id: str, entities: dict) -> str:
    """Mutates `entities` in place (adds a new entry, or records book_id
    against an existing match) and returns the resolved entity_id."""
    name_lc = name.strip().lower()
    for entity in entities["entities"]:
        if entity["type"] != entity_type:
            continue
        aliases_lc = (a.lower() for a in entity["aliases"])
        if name_lc == entity["canonical_name"].lower() or name_lc in aliases_lc:
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
