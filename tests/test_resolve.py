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


def test_plural_and_article_variants_of_the_same_name_unify() -> None:
    """Real observed duplication: "Wargal"/"Wargals"/"The Wargals"/"The
    Wargal" (a creature name from Ranger's Apprentice) each got resolved as
    a separate entity because matching was exact-string-only. All four
    spelling variants of the same entity_type must now resolve to one."""
    entities = {"entities": []}
    base_id = resolve_entity("Wargals", "character", "book-1", entities)

    assert resolve_entity("Wargal", "character", "book-1", entities) == base_id
    assert resolve_entity("The Wargals", "character", "book-1", entities) == base_id
    assert resolve_entity("The Wargal", "character", "book-1", entities) == base_id
    assert len(entities["entities"]) == 1


def test_plural_variant_matching_still_respects_entity_type() -> None:
    """Name normalization must not accidentally relax the existing
    type-scoping - a name typed differently across chapters (the other,
    still-real half of the Wargal duplication bug) is a separate problem
    (see extract/pipeline.py's known_entity_types), not one this
    normalization is meant to paper over silently."""
    entities = {"entities": []}
    character_id = resolve_entity("Wargals", "character", "book-1", entities)
    setting_id = resolve_entity("Wargals", "setting", "book-1", entities)

    assert character_id != setting_id
    assert len(entities["entities"]) == 2
