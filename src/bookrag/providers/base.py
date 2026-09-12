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


def extraction_identity(provider: object) -> str | None:
    """Which provider+model produced a set of facts, e.g.
    "ollama:qwen2.5:7b-instruct" - recorded in extraction_progress.json so a
    resumed run can refuse to continue someone else's work with a different
    model (see pipeline.ExtractionResumeMismatch).

    Deliberately a free function probing an *optional* method rather than a
    required member of the Provider protocol below. Providers are matched
    structurally, and the test suite passes many minimal stand-ins that
    implement extract_facts and nothing else; making this mandatory would
    break them all to serve a bookkeeping concern. Returns None when the
    provider doesn't offer one, which callers must read as "unknown, so
    unverifiable" - never as "a different model".
    """
    describe = getattr(provider, "extraction_identity", None)
    if not callable(describe):
        return None
    try:
        identity = describe()
    except Exception:  # noqa: BLE001 - see below
        # An identity probe exists only to label a run; it must never be the
        # thing that takes one down. A provider whose identity raises is
        # treated exactly like one that has no identity at all.
        return None
    return str(identity) if identity else None


class Provider(Protocol):
    def extract_facts(
        self,
        chapter_text: str,
        known_entities: list[str],
        content_type: str = "fiction",
        known_entity_types: dict[str, str] | None = None,
    ) -> list[ExtractedFact]: ...

    def answer_question(self, question: str, context: str, content_type: str = "fiction") -> str: ...

    # Optional, intentionally not declared here: extraction_identity() ->
    # str. Read it through the module-level extraction_identity() above,
    # which tolerates its absence.
