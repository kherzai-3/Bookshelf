"""Shared types every provider (Claude, a local Ollama model, the test
fake) implements against - both the extraction pipeline and the chat REPL
go through this Protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExtractedFact:
    entity_name: str
    entity_type: str  # fiction: "character"|"setting"|"theme"; nonfiction: "character"|"concept"|"theme"
    category: str
    statement: str


class ExtractionParseError(Exception):
    """Raised when a provider's raw output can't be parsed into facts -
    caught by eval.py to score schema-conformance rather than crashing."""


class Provider(Protocol):
    def extract_facts(
        self, chapter_text: str, known_entities: list[str], content_type: str = "fiction"
    ) -> list[ExtractedFact]: ...

    def answer_question(self, question: str, context: str, content_type: str = "fiction") -> str: ...
