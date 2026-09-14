"""Guards on the prompt text this project actually ships to a model.

These are content tests, not behaviour tests: a prompt is shipped data, and
the failure they exist for is one no other test in this suite can see - a
model faithfully following an instruction that was itself wrong.
"""

from __future__ import annotations

import pytest

from bookrag.providers.prompts import (
    ANSWER_SYSTEM_PROMPTS,
    EXTRACTION_SYSTEM_PROMPTS,
    build_answer_user_message,
    build_user_message,
)

# Proper nouns and distinctive phrases from the real, copyrighted books this
# project was developed against. They are not arbitrary: every one of them
# was present in a shipped prompt at some point, and the first group caused a
# real user-visible bug - a freshly cloned install, extracting an unrelated
# book, reported that its protagonist "was nervous about the Choosing Day".
# That sentence was in EXTRACTION_SYSTEM_PROMPT verbatim as a style example,
# and the model copied it into a book that had never heard of it.
#
# A worked example is worth keeping - it measurably improves a small local
# model's output - but it has to be invented content, so that a leak is
# always wrong about a book rather than plausibly right about a different
# one, and so pipeline.py's grounding check can actually catch it.
_REAL_BOOK_CONTENT = [
    # Ranger's Apprentice
    "Choosing Day",
    "Halt",
    "Morgarath",
    "Celtica",
    "oakleaf",
    "Battleschool",
    "Wargal",
    "Kalkara",
    "Araluen",
    "Redmont",
    # Atomic Habits
    "James Clear",
    "habit stacking",
    "Atomic Habits",
    # Moby Dick
    "Ishmael",
    "Ahab",
    "Pequod",
]

_ALL_PROMPTS = [
    *((f"extraction:{k}", v) for k, v in EXTRACTION_SYSTEM_PROMPTS.items()),
    *((f"answer:{k}", v) for k, v in ANSWER_SYSTEM_PROMPTS.items()),
]


@pytest.mark.parametrize("name,prompt", _ALL_PROMPTS)
@pytest.mark.parametrize("phrase", _REAL_BOOK_CONTENT)
def test_prompt_contains_no_real_book_content(name: str, prompt: str, phrase: str) -> None:
    assert phrase.lower() not in prompt.lower(), (
        f"{name} contains {phrase!r}, from a real book. A model copies prompt "
        f"examples into its output - this exact failure mode shipped once. Use "
        f"invented names and details in prompt examples."
    )


@pytest.mark.parametrize("phrase", _REAL_BOOK_CONTENT)
def test_built_messages_contain_no_real_book_content(phrase: str) -> None:
    """The user-message builders wrap caller-supplied text, but must not
    contribute any book content of their own - the same rule as the system
    prompts, applied to the other half of every request."""
    extraction = build_user_message("", [], {})
    answer = build_answer_user_message("", "")
    assert phrase.lower() not in extraction.lower()
    assert phrase.lower() not in answer.lower()


@pytest.mark.parametrize("name,prompt", [p for p in _ALL_PROMPTS if p[0].startswith("extraction:")])
def test_extraction_prompt_labels_its_example_as_illustrative(name: str, prompt: str) -> None:
    """Decontaminating the example removes the specific leak; saying the
    example is only a format illustration is what discourages the next one,
    whatever names it uses."""
    assert "ILLUSTRATION OF THE OUTPUT FORMAT ONLY" in prompt
    assert "must never appear in your output" in prompt


@pytest.mark.parametrize("name,prompt", [p for p in _ALL_PROMPTS if p[0].startswith("extraction:")])
def test_extraction_prompt_example_facts_carry_a_when_field(name: str, prompt: str) -> None:
    """`when` is required by extraction_response_schema, so an example fact
    without one contradicts the schema the same request enforces. The
    nonfiction example omitted it on every fact until this was caught."""
    # Every example fact object is introduced by "entity_name"; each must be
    # followed by a "when" before the next one starts.
    blocks = prompt.split('"entity_name"')[1:]
    assert blocks, f"{name} has no worked example at all"
    for block in blocks:
        assert '"when"' in block, f"{name} has an example fact with no `when` field"
