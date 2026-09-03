"""Real integration test against a locally running Ollama - skipped, not
failed, on any machine where Ollama isn't reachable (keeps the main suite
green elsewhere while still exercising the real thing here)."""

import urllib.error
import urllib.request

import pytest

from bookrag.providers.ollama_provider import DEFAULT_BASE_URL, OllamaProvider
from bookrag.providers.parsing import ALLOWED_CATEGORIES


def _ollama_available() -> bool:
    try:
        urllib.request.urlopen(f"{DEFAULT_BASE_URL}/api/version", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


@pytest.mark.skipif(not _ollama_available(), reason="Ollama is not reachable on this machine")
def test_ollama_provider_extracts_well_formed_facts_from_a_real_chapter() -> None:
    provider = OllamaProvider()

    facts = provider.extract_facts(
        "Ishmael boarded the Pequod. Captain Ahab paced the deck, brooding over "
        "the white whale that had taken his leg.",
        [],
    )

    assert isinstance(facts, list)
    # Not asserting exact content from a real model - just that the response
    # parsed into well-formed ExtractedFacts without raising ExtractionParseError.
    for fact in facts:
        assert fact.entity_name
        assert fact.entity_type in {"character", "setting", "theme"}
        # Now schema-enforced (extraction_response_schema()'s category enum)
        # rather than just documented - worth verifying end-to-end against
        # the real model, not just parse_facts's own normalization fallback.
        assert fact.category in ALLOWED_CATEGORIES
        assert fact.statement
