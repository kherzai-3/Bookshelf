from bookrag.extract.resolve import group_name_variants, resolve_entity


def test_group_name_variants_keeps_two_peoples_name_pairs_apart() -> None:
    """The property the whole function exists for. `looks_like_a_name_variant`
    answers a question about a *pair*, and a caller that collects every name
    with any partner and treats the result as one set fuses unrelated people.
    Two pairs must stay two groups.

    `ingest.vocatives.auto_link_plan` is the caller this was built for, and it
    links without asking at ingest - so the flattened version silently declared
    two first-person narrators to be one character."""
    groups = group_name_variants(["Conn", "Connwaer", "Row", "Rowena"])

    assert sorted(sorted(g) for g in groups) == [["Conn", "Connwaer"], ["Row", "Rowena"]]


def test_group_name_variants_is_transitive_and_keeps_a_loner_alone() -> None:
    """Three spellings of one name are one group, not two overlapping pairs;
    an unrelated name is a group of one, which callers requiring 2+ members
    then ignore for free."""
    groups = group_name_variants(["Conn", "Connwaer", "Connwaerdin", "Magister"])

    assert sorted(sorted(g) for g in groups) == [["Conn", "Connwaer", "Connwaerdin"], ["Magister"]]


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


def test_a_later_series_book_reuses_the_earlier_books_entity() -> None:
    """The point of sharing identity across books: book 2 must not
    re-introduce a character book 1 already established. Requires an
    explicit scope naming both books - normally
    storage.series_reading_order(book_id)."""
    entities = {"entities": []}
    entity_id = resolve_entity("Ahab", "character", "moby-dick", entities)

    same_id = resolve_entity(
        "Ahab", "character", "moby-dick-2", entities, scope=["moby-dick", "moby-dick-2"]
    )

    assert same_id == entity_id
    assert entities["entities"][0]["book_ids"] == ["moby-dick", "moby-dick-2"]


def test_unrelated_books_sharing_a_name_stay_separate_entities() -> None:
    """entities.json is one global registry, and before identity was scoped
    the match loop ran over every book ever ingested - so any two books
    sharing a common first name became one person. Real observed case in a
    four-book library: a "Michael" in Ranger's Apprentice and a "Michael" in
    Moby Dick merged into a single entity claiming both books, alongside
    "George", "Power" and "Prediction".

    A fact's own facts.jsonl is per-book, so this never leaked facts between
    books - what it corrupted is the registry's answer to "who is this and
    where do they appear", which is exactly what any cross-book/series
    feature would be built on."""
    entities = {"entities": []}
    rangers_id = resolve_entity("Michael", "character", "rangers-apprentice", entities)

    moby_id = resolve_entity("Michael", "character", "moby-dick", entities)

    assert moby_id != rangers_id
    assert len(entities["entities"]) == 2
    assert [e["book_ids"] for e in entities["entities"]] == [["rangers-apprentice"], ["moby-dick"]]


def test_scope_defaults_to_the_book_itself_rather_than_every_book() -> None:
    """The default is the narrow, safe scope on purpose. Too narrow
    duplicates an entity within a series - visible, and repairable by
    `bookrag doctor`. Too wide silently fuses two unrelated books'
    characters into one record. A caller that forgets to pass a scope gets
    the recoverable failure, not the silent one."""
    entities = {"entities": []}
    resolve_entity("Ahab", "character", "moby-dick", entities)

    unscoped_id = resolve_entity("Ahab", "character", "some-other-book", entities)

    assert unscoped_id != entities["entities"][0]["entity_id"]


def test_scope_does_not_override_type_scoping() -> None:
    """Being in scope is necessary, not sufficient - the existing
    (name, type) rule still applies on top of it."""
    entities = {"entities": []}
    scope = ["book-1", "book-2"]
    character_id = resolve_entity("Nantucket", "character", "book-1", entities, scope=scope)

    setting_id = resolve_entity("Nantucket", "setting", "book-2", entities, scope=scope)

    assert character_id != setting_id


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
