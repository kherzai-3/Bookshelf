"""Shared prompts - every provider is given the same instructions for a
given task, so the eval harness compares providers/models, not incidental
differences in prompt wording."""

from __future__ import annotations

EXTRACTION_SYSTEM_PROMPT = """You extract structured facts about characters, settings, \
and themes from a single chapter of a novel.

Respond with ONLY a JSON object of the shape {"facts": [...]}, no prose, no \
markdown fences. Each element of "facts" is:
{"entity_name": str, "entity_type": "character"|"setting"|"theme",
 "category": str, "statement": str}

category must be one of:
- personality: a character trait, attitude, or way of thinking.
- appearance: a physical description.
- relationship: how one entity relates to another (ally, enemy, family, etc).
- status: a concrete, factual change in role, rank, allegiance, or \
life-condition (e.g. "became Halt's apprentice", "was accepted into \
Battleschool", "is now the King's champion") - reserve this for milestone \
changes, not fleeting reactions or feelings.
- description: a general fact about a setting or theme, or anything that \
doesn't fit the other categories.
- development: a notable action, decision, or event involving the entity \
that doesn't itself change their status.

Every statement must be self-contained and understandable on its own, \
without needing the surrounding chapter text - name the entity or clearly \
state what happened, rather than a bare pronoun with no context (write \
"Will felt nervous about the Choosing Day" rather than "he knew it all too \
well"). Do not respond with sentence fragments, single words, or \
unattributed dialogue quotes with no context.

Only report something if it is directly and explicitly stated or shown in \
the chapter text below - never invent a detail, and never introduce an \
entity whose name doesn't appear in the text. If this chapter's text is not \
part of the story's narrative (e.g. a copyright notice, dedication, table \
of contents, or author biography), or if nothing about a character, \
setting, or theme is revealed, return {"facts": []}.

Example:
Chapter text: "Will scrambled over the wall, breathing hard. Halt handed \
him the silver oakleaf without a word - the mark of a fully fledged \
Ranger. Will's hands trembled as he took it."

{"facts": [
  {"entity_name": "Will", "entity_type": "character", "category": "status", \
"statement": "Will received the silver oakleaf from Halt, marking him as a \
fully fledged Ranger."},
  {"entity_name": "Will", "entity_type": "character", "category": \
"personality", "statement": "Will's hands trembled with emotion as he \
received the oakleaf."}
]}"""


def build_user_message(chapter_text: str, known_entities: list[str]) -> str:
    known = ", ".join(known_entities) if known_entities else "(none yet)"
    return (
        f"Entities already introduced earlier in the book (use these exact "
        f"names if you're referring to the same person/place, rather than "
        f"inventing a new name for someone already known): {known}\n\n"
        f"Chapter text:\n{chapter_text}"
    )


ANSWER_SYSTEM_PROMPT = """You answer a reader's question about a novel using \
ONLY the facts provided below - never anything else you might know about \
this book or its characters from elsewhere. The facts are deliberately \
limited to what has happened up to the reader's current point in the book, \
so they must never be supplemented with outside knowledge, which could spoil \
something not yet reached.

Facts are grouped by character/setting/theme, then by category (e.g. \
status, personality, appearance), with each individual fact tagged by the \
chapter it came from, e.g. "[ch 9] has completed the Choosing Day." \
Chapters are always listed in increasing order within a group. When two \
facts in the SAME category for the SAME entity describe conflicting states \
(e.g. one chapter says something hasn't happened yet, a later chapter says \
it has), trust the fact from the LATER chapter as the current, correct \
state - characters and circumstances change as the story progresses, and an \
earlier fact can simply be outdated. Facts in different categories, or \
about different specifics within a category, are NOT conflicts - treat them \
as accumulated knowledge about that entity, not contradictions to pick \
between.

If the provided facts don't contain enough information to answer, say so \
plainly (e.g. "I don't have enough information about that yet") rather than \
guessing or inventing an answer."""


def build_answer_user_message(question: str, context: str) -> str:
    return f"Known facts:\n{context}\n\nQuestion: {question}"
