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


# A parallel prompt, not a parameterized version of the one above -
# confirmed necessary, not just theoretically different, by a real
# checkpoint run (bookrag eval against consolidated Atomic Habits
# chapters): the fiction prompt/categories collapsed almost everything into
# "description", and "setting" produced outright nonsense - "desk",
# "phone", "bedroom", "coffee shop" all filed as cataloged story settings,
# when they were just illustrative examples in a discussion of habit cues.
# See providers/parsing.py's ALLOWED_CATEGORIES_NONFICTION/
# ALLOWED_ENTITY_TYPES_NONFICTION for the taxonomy this prompt must match.
EXTRACTION_SYSTEM_PROMPT_NONFICTION = """You extract structured facts about concepts, \
techniques, and real people/examples from a single chapter of a nonfiction book.

Respond with ONLY a JSON object of the shape {"facts": [...]}, no prose, no \
markdown fences. Each element of "facts" is:
{"entity_name": str, "entity_type": "character"|"concept"|"theme",
 "category": str, "statement": str}

category must be one of:
- definition: what a concept or technique fundamentally is, in the \
author's own terms (e.g. "a habit is a routine or behavior performed \
automatically").
- claim: an assertion about cause and effect, human behavior, or the \
world - not itself an instruction to act.
- technique: a concrete, actionable instruction the reader is told to do \
(e.g. "pair a new habit with an existing one").
- example: an illustrative anecdote, case study, or real-world instance \
supporting a claim, technique, or definition.
- relationship: how one concept relates to, builds on, or is a component \
of another (not a relationship between people).
- description: a general fact about a person, concept, or theme, or \
anything that doesn't fit the other categories.

Every statement must be self-contained and understandable on its own, \
without needing the surrounding chapter text - name the concept or person, \
or clearly state what's being claimed, rather than a bare pronoun with no \
context. Do not respond with sentence fragments, single words, or \
unattributed dialogue quotes with no context.

Only report something if it is directly and explicitly stated or shown in \
the chapter text below - never invent a detail, and never introduce an \
entity whose name doesn't appear in the text. If this chapter's text is \
front or back matter rather than the book's actual content (e.g. a \
copyright notice, dedication, table of contents, index, acknowledgments, \
or promotional material for another book), or if nothing about a concept, \
person, or theme is revealed, return {"facts": []}.

Example:
Chapter text: "One of the most effective ways to build a new habit is to \
pair it with one you already do every day. James Clear calls this habit \
stacking."

{"facts": [
  {"entity_name": "Habit Stacking", "entity_type": "concept", "category": \
"technique", "statement": "Pair a new habit with an existing daily habit \
using the formula: after the current habit, do the new habit."},
  {"entity_name": "James Clear", "entity_type": "character", "category": \
"description", "statement": "James Clear coined the term habit stacking."}
]}"""

EXTRACTION_SYSTEM_PROMPTS = {"fiction": EXTRACTION_SYSTEM_PROMPT, "nonfiction": EXTRACTION_SYSTEM_PROMPT_NONFICTION}


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


# format_context (query.py) needs no changes for nonfiction - it groups
# purely by entity_id/category with no fiction-specific strings anywhere.
# Only the prose explaining that shape to the answering model needs a
# nonfiction-flavored twin: "spoiler" reads oddly for a self-help book
# (nothing is "spoiled" by an early technique) - reframed around reading
# progress instead.
ANSWER_SYSTEM_PROMPT_NONFICTION = """You answer a reader's question about a nonfiction book \
using ONLY the facts provided below - never anything else you might know \
about this book or its subject from elsewhere. The facts are deliberately \
limited to what has been covered up to the reader's current point in the \
book, so they must never be supplemented with outside knowledge - a later \
chapter may define a term, introduce a technique, or refine an earlier \
claim in a way the reader hasn't reached yet.

Facts are grouped by concept/person/theme, then by category (e.g. \
technique, definition, claim), with each individual fact tagged by the \
chapter it came from, e.g. "[ch 9] pair a new habit with an existing one." \
Chapters are always listed in increasing order within a group. When two \
facts in the SAME category for the SAME entity describe conflicting or \
updated information (e.g. a claim refined or corrected later in the \
book), trust the fact from the LATER chapter as the current, most \
complete version. Facts in different categories, or about different \
specifics within a category, are NOT conflicts - treat them as \
accumulated knowledge, not contradictions to pick between.

If the provided facts don't contain enough information to answer, say so \
plainly (e.g. "I don't have enough information about that yet") rather than \
guessing or inventing an answer."""

ANSWER_SYSTEM_PROMPTS = {"fiction": ANSWER_SYSTEM_PROMPT, "nonfiction": ANSWER_SYSTEM_PROMPT_NONFICTION}


def build_answer_user_message(question: str, context: str) -> str:
    return f"Known facts:\n{context}\n\nQuestion: {question}"
