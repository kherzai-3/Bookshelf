from bookrag.providers.fake_provider import FakeProvider


def test_extracts_one_fact_per_new_proper_noun() -> None:
    provider = FakeProvider()

    facts = provider.extract_facts("Ishmael went to sea. Ahab commanded the ship.", [])

    assert [f.entity_name for f in facts] == ["Ishmael", "Ahab"]
    assert "Ishmael went to sea" in facts[0].statement
    assert "Ahab commanded the ship" in facts[1].statement


def test_repeated_names_only_produce_one_fact() -> None:
    provider = FakeProvider()

    facts = provider.extract_facts("Ahab spoke. Ahab spoke again.", [])

    assert [f.entity_name for f in facts] == ["Ahab"]


def test_common_sentence_starters_are_not_treated_as_entities() -> None:
    provider = FakeProvider()

    facts = provider.extract_facts("The sea was calm. He waited.", [])

    assert facts == []
