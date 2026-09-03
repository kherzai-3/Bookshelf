from bookrag.extract.resolve import resolve_entity


def test_new_name_creates_a_new_entity() -> None:
    entities = {"entities": []}

    entity_id = resolve_entity("Ishmael", "character", "moby-dick", entities)

    assert len(entities["entities"]) == 1
    entry = entities["entities"][0]
    assert entry["entity_id"] == entity_id
    assert entry["canonical_name"] == "Ishmael"
    assert entry["book_ids"] == ["moby-dick"]


def test_case_insensitive_exact_match_reuses_existing_entity() -> None:
    entities = {"entities": []}
    first_id = resolve_entity("Ishmael", "character", "moby-dick", entities)

    second_id = resolve_entity("ishmael", "character", "moby-dick", entities)

    assert second_id == first_id
    assert len(entities["entities"]) == 1


def test_alias_match_reuses_existing_entity() -> None:
    entities = {
        "entities": [
            {
                "entity_id": "character-abc123",
                "canonical_name": "Ishmael",
                "type": "character",
                "aliases": ["the narrator"],
                "book_ids": ["moby-dick"],
            }
        ]
    }

    entity_id = resolve_entity("The Narrator", "character", "moby-dick", entities)

    assert entity_id == "character-abc123"
    assert len(entities["entities"]) == 1


def test_same_name_different_type_creates_separate_entities() -> None:
    entities = {"entities": []}
    char_id = resolve_entity("Nantucket", "character", "moby-dick", entities)
    setting_id = resolve_entity("Nantucket", "setting", "moby-dick", entities)

    assert char_id != setting_id
    assert len(entities["entities"]) == 2


def test_new_book_id_gets_added_to_existing_entitys_book_ids() -> None:
    entities = {"entities": []}
    entity_id = resolve_entity("Ahab", "character", "moby-dick", entities)

    same_id = resolve_entity("Ahab", "character", "moby-dick-2", entities)

    assert same_id == entity_id
    assert entities["entities"][0]["book_ids"] == ["moby-dick", "moby-dick-2"]
