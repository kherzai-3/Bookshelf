"""Real extraction provider using the Anthropic API."""

from __future__ import annotations

import os

from bookrag.providers.base import ExtractedFact
from bookrag.providers.parsing import parse_facts
from bookrag.providers.prompts import (
    ANSWER_SYSTEM_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    build_answer_user_message,
    build_user_message,
)

DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicProvider:
    def __init__(self, model: str | None = None) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set (checked environment and .env). "
                "Set it before using the anthropic provider."
            )
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    def extract_facts(self, chapter_text: str, known_entities: list[str]) -> list[ExtractedFact]:
        raw_text = self._complete(EXTRACTION_SYSTEM_PROMPT, build_user_message(chapter_text, known_entities))
        return parse_facts(raw_text)

    def answer_question(self, question: str, context: str) -> str:
        return self._complete(ANSWER_SYSTEM_PROMPT, build_answer_user_message(question, context))

    def _complete(self, system: str, user_message: str) -> str:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
