import pytest

from bookrag.providers.base import ExtractionParseError
from bookrag.providers.parsing import (
    ALLOWED_CATEGORIES,
    ALLOWED_CATEGORIES_NONFICTION,
    ALLOWED_ENTITY_TYPES,
    ALLOWED_ENTITY_TYPES_NONFICTION,
    extraction_response_schema,
    parse_facts,
)

_FACT = '{"entity_name": "Ishmael", "entity_type": "character", "category": "development", "statement": "went to sea"}'


def test_parses_a_bare_json_array() -> None:
    facts = parse_facts(f"[{_FACT}]")

    assert len(facts) == 1
    assert facts[0].entity_name == "Ishmael"


def test_strips_markdown_code_fences() -> None:
    facts = parse_facts(f"```json\n[{_FACT}]\n```")

    assert len(facts) == 1


def test_unwraps_a_dict_wrapping_the_list() -> None:
    facts = parse_facts(f'{{"facts": [{_FACT}]}}')

    assert len(facts) == 1
    assert facts[0].entity_name == "Ishmael"


def test_wraps_a_single_bare_object_in_a_list() -> None:
    facts = parse_facts(_FACT)

    assert len(facts) == 1
    assert facts[0].entity_name == "Ishmael"


def test_empty_array_returns_no_facts() -> None:
    assert parse_facts("[]") == []


def test_empty_object_returns_no_facts() -> None:
    """Real case: qwen2.5:7b-instruct returned "{}" for a chapter with no
    real character content (a table-of-contents page) - correctly
    reporting nothing to extract, rather than hallucinating a fact like
    llama3.2:3b did on the same chapter. {} must not be treated as one
    malformed fact object missing all its keys."""
    assert parse_facts("{}") == []


def test_invalid_json_raises_extraction_parse_error() -> None:
    with pytest.raises(ExtractionParseError):
        parse_facts("this is not json at all")


def test_missing_required_field_raises_extraction_parse_error() -> None:
    with pytest.raises(ExtractionParseError):
        parse_facts('[{"entity_name": "Ishmael"}]')


def test_setting_and_theme_entity_types_pass_through_unchanged() -> None:
    fact = '{"entity_name": "Nantucket", "entity_type": "setting", "category": "description", "statement": "an island"}'

    facts = parse_facts(f"[{fact}]")

    assert facts[0].entity_type == "setting"


def test_known_alias_is_normalized_to_the_real_type() -> None:
    """Regression test: a real run against llama3.2:3b produced "monster"
    and "creature" as entity_type for real creatures (Kalkara, Wargal) -
    these must fold into "character" rather than becoming their own types,
    since resolve_entity() matches on (name, type) together and a drifting
    type string would make the same real entity fail to match itself on a
    later extraction, silently duplicating it instead of reusing it."""
    fact = '{"entity_name": "Kalkara", "entity_type": "monster", "category": "description", "statement": "a fearsome beast"}'

    facts = parse_facts(f"[{fact}]")

    assert facts[0].entity_type == "character"


def test_unrecognized_entity_type_is_rejected_not_silently_accepted() -> None:
    """"Enforce a stricter type list" means an unknown category is a visible
    failure (counted, reviewable), not a new type quietly added forever."""
    fact = '{"entity_name": "The Rangers", "entity_type": "faction", "category": "description", "statement": "a group"}'

    with pytest.raises(ExtractionParseError):
        parse_facts(f"[{fact}]")


def test_entity_type_normalization_is_case_insensitive() -> None:
    fact = '{"entity_name": "Kalkara", "entity_type": "Monster", "category": "description", "statement": "x"}'

    facts = parse_facts(f"[{fact}]")

    assert facts[0].entity_type == "character"


def test_unrecognized_category_is_normalized_not_rejected() -> None:
    """Real observed drift (llama3.2:3b, no schema enforcement yet):
    "location" and "author" both leaked through as category values beyond
    the documented six. Unlike entity_type, category doesn't gate entity
    deduplication, so an unrecognized value is folded into "description"
    rather than failing the whole fact/chapter."""
    fact = '{"entity_name": "The Docks", "entity_type": "setting", "category": "location", "statement": "a busy port"}'

    facts = parse_facts(f"[{fact}]")

    assert facts[0].category == "description"


def test_known_category_passes_through_unchanged() -> None:
    fact = '{"entity_name": "Will", "entity_type": "character", "category": "status", "statement": "became an apprentice"}'

    facts = parse_facts(f"[{fact}]")

    assert facts[0].category == "status"


def test_category_normalization_is_case_insensitive() -> None:
    fact = '{"entity_name": "Will", "entity_type": "character", "category": "Status", "statement": "x"}'

    facts = parse_facts(f"[{fact}]")

    assert facts[0].category == "status"


def test_corrupted_statement_is_dropped_not_persisted() -> None:
    """Real observed corruption: a response tried to emit 4 facts, but used
    typographic curly quotes for the later ones' JSON keys instead of a real
    closing '"' - json.loads() still succeeded (syntactically valid JSON),
    but 3 facts vanished into the first one's `statement`, which ended up
    containing literal '"entity_name"' text from the swallowed objects. The
    corrupted fact must be dropped, not the whole response."""
    clean = '{"entity_name": "Erak", "entity_type": "character", "category": "relationship", "statement": "trusts Will"}'
    corrupted = (
        '{"entity_name": "Erak", "entity_type": "character", "category": "relationship", '
        '"statement": "I\'ll honour any undertaking I\'ve made.\\u201d} {\\u201centity_name\\u201d: '
        '\\u201cEvanlyn\\u201d, \\u201centity_type\\u201d: \\u201ccharacter\\u201d}"}'
    )

    facts = parse_facts(f"[{clean}, {corrupted}]")

    assert len(facts) == 1
    assert facts[0].statement == "trusts Will"


def test_overlong_statement_is_dropped() -> None:
    fact = (
        '{"entity_name": "Will", "entity_type": "character", "category": "development", '
        f'"statement": "{"x" * 600}"}}'
    )

    assert parse_facts(f"[{fact}]") == []


def test_extraction_response_schema_enumerates_allowed_types_and_categories() -> None:
    schema = extraction_response_schema()

    fact_schema = schema["properties"]["facts"]["items"]
    assert set(fact_schema["properties"]["entity_type"]["enum"]) == ALLOWED_ENTITY_TYPES
    assert set(fact_schema["properties"]["category"]["enum"]) == ALLOWED_CATEGORIES
    assert fact_schema["required"] == ["entity_name", "entity_type", "category", "statement"]
    assert schema["required"] == ["facts"]


def test_extraction_response_schema_caps_facts_array_length() -> None:
    """Real observed failure with no cap: a request generated 8,490+ output
    tokens (normal chapters produce 500-1500) over 14m43s before Ollama's
    own server gave up and restarted - a runaway generation loop under
    grammar-constrained decoding, which has no structural reason to ever
    close an open-ended array. maxItems makes that impossible, not just
    unlikely."""
    schema = extraction_response_schema()

    assert schema["properties"]["facts"]["maxItems"] == 40


def test_extraction_response_schema_of_nonfiction_uses_the_nonfiction_taxonomy() -> None:
    schema = extraction_response_schema(content_type="nonfiction")

    fact_schema = schema["properties"]["facts"]["items"]
    assert set(fact_schema["properties"]["entity_type"]["enum"]) == ALLOWED_ENTITY_TYPES_NONFICTION
    assert set(fact_schema["properties"]["category"]["enum"]) == ALLOWED_CATEGORIES_NONFICTION


def test_parse_facts_of_nonfiction_accepts_a_nonfiction_category_and_type() -> None:
    fact = (
        '{"entity_name": "Habit Stacking", "entity_type": "concept", "category": "technique", '
        '"statement": "pair a new habit with an existing one"}'
    )

    facts = parse_facts(f"[{fact}]", content_type="nonfiction")

    assert facts[0].entity_type == "concept"
    assert facts[0].category == "technique"


def test_parse_facts_of_nonfiction_rejects_a_fiction_only_entity_type() -> None:
    """"setting" is deliberately dropped for nonfiction - real observed
    failure without this: generic illustrative nouns ("desk", "phone",
    "bedroom") got cataloged as if they were meaningful recurring story
    settings, when they were just examples in a discussion of habit cues."""
    fact = '{"entity_name": "the kitchen counter", "entity_type": "setting", "category": "example", "statement": "x"}'

    with pytest.raises(ExtractionParseError):
        parse_facts(f"[{fact}]", content_type="nonfiction")


def test_parse_facts_of_nonfiction_normalizes_an_unrecognized_category_leniently() -> None:
    fact = '{"entity_name": "Habits", "entity_type": "theme", "category": "location", "statement": "x"}'

    facts = parse_facts(f"[{fact}]", content_type="nonfiction")

    assert facts[0].category == "description"
