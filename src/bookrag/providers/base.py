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
    # Where the fact sits in *story* time, as opposed to the chapter that
    # revealed it. "present" (the chapter's own narrative moment), "past"
    # (recounted backstory, possibly predating the book entirely), "future"
    # (anticipated or planned). Defaults to "present" because that is what
    # the large majority of facts are, and because every fact extracted
    # before this field existed is one.
    when: str = "present"
    # The text's own words for when it happened ("fifteen years ago", "the
    # next morning"), copied verbatim when the chapter states one. Displayed
    # to the reader, never parsed - see parsing.py's context doc.
    time_phrase: str | None = None


class ExtractionParseError(Exception):
    """Raised when a provider's raw output can't be parsed into facts -
    caught by eval.py to score schema-conformance rather than crashing."""


class Provider(Protocol):
    def extract_facts(
        self,
        chapter_text: str,
        known_entities: list[str],
        content_type: str = "fiction",
        known_entity_types: dict[str, str] | None = None,
    ) -> list[ExtractedFact]: ...

    def answer_question(self, question: str, context: str, content_type: str = "fiction") -> str: ...
