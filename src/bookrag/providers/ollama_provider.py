"""Local extraction provider using Ollama's REST API - no API key required,
inference runs entirely on this machine. Uses stdlib urllib rather than
adding an HTTP client dependency, since it's just one JSON POST."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from bookrag.providers.base import ExtractedFact
from bookrag.providers.parsing import extraction_response_schema, parse_facts
from bookrag.providers.prompts import (
    ANSWER_SYSTEM_PROMPTS,
    EXTRACTION_SYSTEM_PROMPTS,
    build_answer_user_message,
    build_user_message,
)

DEFAULT_MODEL = "llama3.2:3b"
DEFAULT_BASE_URL = "http://localhost:11434"
# Raised from an initial 8192 after a real confirmed overflow: bookrag
# chat's context (query.format_context) has no size cap of its own by
# design (see that module's docstring) and grows with the whole book's
# fact count - a real full-length novel's assembled context measured at
# ~26,000-30,000 tokens by its final chapters, 3-4x this window, meaning
# the model was silently never seeing most of what it was asked about.
# 16384 is still a bounded, deliberate choice, not "big enough for
# anything" - query.select_relevant_facts (added alongside this) is the
# real, scalable fix (only relevant facts are sent at all, so context size
# stops growing with book length); this is a safety-net baseline for
# whatever still reaches the model after that filtering (e.g. a broad
# question naming no specific entity, which still gets everything).
DEFAULT_NUM_CTX = 16384
# Raised from an initial 300s - the extraction prompt rewrite (dropping the
# unenforceable "only new/changed" instruction, adding per-category
# definitions and a worked example) produces far more facts per chapter than
# before, and known_entities grows faster as a result, both lengthening
# later chapters' calls. Real observed case: a chapter past #10 in a real
# 75-chapter run exceeded 300s even with nothing else competing for the same
# local Ollama instance - not a per-token slowdown from schema-constrained
# decoding itself (measured comparable per-token speed to plain
# format:"json"), just more output to generate as the book progresses.
DEFAULT_TIMEOUT_SECONDS = 900
# Lower than Ollama's own default (~0.8) - extraction is a structured task,
# not a creative one, and a lower temperature produces more consistent,
# schema-conformant output. Not applied to answer_question, which is a
# conversational answer and benefits from Ollama's normal default instead.
DEFAULT_EXTRACTION_TEMPERATURE = 0.2


class OllamaProvider:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        num_ctx: int | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        self._base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self._num_ctx = num_ctx or int(os.environ.get("OLLAMA_NUM_CTX", DEFAULT_NUM_CTX))
        self._timeout = timeout

    def extract_facts(
        self,
        chapter_text: str,
        known_entities: list[str],
        content_type: str = "fiction",
        known_entity_types: dict[str, str] | None = None,
    ) -> list[ExtractedFact]:
        content = self._chat(
            EXTRACTION_SYSTEM_PROMPTS[content_type],
            build_user_message(chapter_text, known_entities, known_entity_types),
            # A full JSON Schema, not just the string "json" - grammar-
            # constrains sampling so entity_type/category can never drift
            # outside their enums and `statement` can't grow past its
            # maxLength, rather than merely hoping the model's prose-shaped
            # output happens to match (verified empirically against this
            # project's local Ollama to hold even adversarially).
            response_format=extraction_response_schema(content_type),
            temperature=DEFAULT_EXTRACTION_TEMPERATURE,
        )
        return parse_facts(content, content_type)

    def answer_question(self, question: str, context: str, content_type: str = "fiction") -> str:
        # No response_format/temperature override here - a chat answer is
        # free text, not a structured fact list, and benefits from Ollama's
        # normal conversational sampling defaults.
        return self._chat(ANSWER_SYSTEM_PROMPTS[content_type], build_answer_user_message(question, context))

    def _chat(
        self,
        system: str,
        user_message: str,
        *,
        response_format: dict | None = None,
        temperature: float | None = None,
    ) -> str:
        options = {
            # Ollama's default context window (4096 tokens) can be exceeded
            # by a long chapter (observed: real chapters up to ~3865 words,
            # roughly 5000+ tokens once the system prompt and known-entities
            # list are added) - raised explicitly rather than relying on the
            # default and hoping every chapter stays under it.
            "num_ctx": self._num_ctx,
        }
        if temperature is not None:
            options["temperature"] = temperature

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": options,
        }
        if response_format is not None:
            payload["format"] = response_format

        request = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            # A slow/stuck response past `timeout` raises a bare TimeoutError
            # (real, observed: a single request during a live extraction run
            # stalled and surfaced as an unhelpful bare "timed out" before
            # this was caught here) rather than URLError - both mean the same
            # thing from the caller's perspective, so both get the same
            # actionable message.
            raise RuntimeError(
                f"Could not reach Ollama at {self._base_url} (or it didn't respond within "
                f"{self._timeout}s) - is it running? "
                f"(install: https://ollama.com, then `ollama pull {self._model}`) - {exc}"
            ) from exc

        return body.get("message", {}).get("content", "")
