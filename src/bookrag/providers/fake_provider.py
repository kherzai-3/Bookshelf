"""Deterministic, no-network provider - lets the extraction pipeline be
tested without an API key. Not meant to produce good extractions, just
predictable ones: one fact per new capitalized word per chapter, with the
sentence it appeared in as the statement."""

from __future__ import annotations

import re

from bookrag.providers.base import ExtractedFact

_STOPWORDS = {"The", "A", "An", "I", "He", "She", "They", "It", "We", "You"}
_PROPER_NOUN = re.compile(r"\b[A-Z][a-z]+\b")


class FakeProvider:
    def extract_facts(
        self,
        chapter_text: str,
        known_entities: list[str],
        content_type: str = "fiction",
        known_entity_types: dict[str, str] | None = None,
    ) -> list[ExtractedFact]:
        # content_type/known_entity_types are accepted for Provider protocol
        # compatibility but ignored - this double is deliberately dumb/
        # predictable regardless of content type (see module docstring), not
        # a realistic stand-in for either taxonomy.
        facts: list[ExtractedFact] = []
        seen: set[str] = set()
        for sentence in re.split(r"(?<=[.!?])\s+", chapter_text):
            for match in _PROPER_NOUN.finditer(sentence):
                name = match.group(0)
                if name in _STOPWORDS or name in seen:
                    continue
                seen.add(name)
                facts.append(
                    ExtractedFact(
                        entity_name=name,
                        entity_type="character",
                        category="development",
                        statement=sentence.strip(),
                    )
                )
        return facts

    def answer_question(self, question: str, context: str, content_type: str = "fiction") -> str:
        if not context.strip():
            return "I don't have enough information about that yet."
        return f"[fake answer] Based on: {context}"
