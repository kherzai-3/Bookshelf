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
- appearance: a physical description - hair, build, clothing, scars, or any \
other distinguishing physical detail. These are easy to miss when they're \
mentioned in passing during action or dialogue rather than as a dedicated \
description paragraph (e.g. a character's cloak or hair color mentioned \
mid-scene, not introduced with "he looked like..."). Actively look for \
appearance details anywhere in the text, not only in obvious introduction/ \
description passages.
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

Never report the same fact more than once, even if the chapter repeats it \
or returns to it multiple times (e.g. the same request or action recurring \
across several paragraphs) - state each distinct fact a single time only, \
no matter how many times it happens or how important it feels.

Stop once you have reported every fact concretely and specifically stated \
in the chapter text - do not keep inventing additional vague or generic \
statements (e.g. a list of abstract virtues or lessons an entity is \
supposedly "learning about") just to report more. A short, precise list of \
real facts is always better than a longer list padded with restated or \
unspecific filler.

If a single sentence or moment reveals more than one kind of fact, report \
it as separate facts, one per relevant category, rather than filing it \
under only one (e.g. "he stroked his grey-flecked beard thoughtfully" is \
BOTH an appearance detail - he has a grey-flecked beard - AND a \
personality/mood cue - he was being thoughtful; report both, don't pick \
just one).

Only report something if it is directly and explicitly stated or shown in \
the chapter text below - never invent a detail, and never introduce an \
entity whose name doesn't appear in the text. If this chapter's text is not \
part of the story's narrative (e.g. a copyright notice, dedication, table \
of contents, or author biography), or if nothing about a character, \
setting, or theme is revealed, return {"facts": []}.

Example:
Chapter text: "Will scrambled over the wall, breathing hard. Halt handed \
him the silver oakleaf without a word - the mark of a fully fledged \
Ranger. Will's hands trembled as he took it. Halt stroked his grey-flecked \
beard thoughtfully, his cloak already blending into the shadows of the \
trees as he turned away."

{"facts": [
  {"entity_name": "Will", "entity_type": "character", "category": "status", \
"statement": "Will received the silver oakleaf from Halt, marking him as a \
fully fledged Ranger."},
  {"entity_name": "Will", "entity_type": "character", "category": \
"personality", "statement": "Will's hands trembled with emotion as he \
received the oakleaf."},
  {"entity_name": "Halt", "entity_type": "character", "category": \
"appearance", "statement": "Halt has a grey-flecked beard."},
  {"entity_name": "Halt", "entity_type": "character", "category": \
"personality", "statement": "Halt stroked his beard thoughtfully."},
  {"entity_name": "Halt", "entity_type": "character", "category": \
"appearance", "statement": "Halt wears a grey cloak that blends into \
shadows."}
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

Never report the same fact more than once, even if the chapter repeats or \
returns to it multiple times - state each distinct fact a single time \
only. Stop once you have reported every fact concretely and specifically \
stated in the chapter text - do not keep inventing additional vague or \
generic statements just to report more. A short, precise list of real \
facts is always better than a longer list padded with restated or \
unspecific filler.

If a single sentence or passage reveals more than one kind of fact, report \
it as separate facts, one per relevant category, rather than filing it \
under only one (e.g. a sentence that both defines a concept AND gives a \
concrete instruction for applying it is both a "definition" fact and a \
"technique" fact; report both, don't pick just one).

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


def build_user_message(
    chapter_text: str, known_entities: list[str], known_entity_types: dict[str, str] | None = None
) -> str:
    known_entity_types = known_entity_types or {}
    if known_entities:
        known = ", ".join(
            f"{name} ({known_entity_types[name]})" if name in known_entity_types else name
            for name in known_entities
        )
    else:
        known = "(none yet)"
    return (
        f"Entities already introduced earlier in the book, with the type each "
        f"was already recorded as (use the exact same name AND type if you're "
        f"referring to the same person/place, rather than inventing a new name "
        f"or filing it under a different type): {known}\n\n"
        f"Chapter text:\n{chapter_text}"
    )


ANSWER_SYSTEM_PROMPT = """You answer a reader's question about a novel using \
ONLY the facts provided below - never anything else you might know about \
this book or its characters from elsewhere. The facts are deliberately \
limited to what has happened up to the reader's current point in the book, \
so they must never be supplemented with outside knowledge, which could spoil \
something not yet reached.

Facts are grouped by character/setting/theme, and each individual fact is \
tagged by the chapter it came from, e.g. "[ch 9] has completed the Choosing \
Day." Chapters are always listed in increasing order. Within each entity the \
facts are split into two kinds, and they must be read DIFFERENTLY:

- Lines under "What happened, in order" are SEPARATE MOMENTS in the story. A \
later line never corrects, replaces, or concludes an earlier one - both \
things simply happened, at different times. Never merge two of these into a \
single claim, and never assume one caused or resolved the other unless a \
fact explicitly says so. Two entries that sound contradictory are usually \
two different occasions, not a correction. If the reader asks what happened \
to someone, walk through the sequence rather than picking one line.
- Lines under "Standing description" describe how something simply IS. Here, \
when two lines in the same category genuinely conflict (a rank, an age, a \
location can only have one current value), trust the LATER chapter as the \
current state - an earlier one can simply be outdated.

Facts in different categories, or about different specifics within a \
category, are NOT conflicts - treat them as accumulated knowledge about that \
entity, not contradictions to pick between.

A question about a specific kind of detail is NOT limited to the category \
whose label matches that topic - relevant details can appear under any \
category. For example, a question about what someone looks like should be \
answered using every visually-relevant detail you can find for that \
entity, not only facts tagged "appearance" - a fact tagged "personality" or \
"status" can still mention a physical feature, a gesture, or clothing (e.g. \
"stroked his beard gravely" reveals he has a beard even though it's filed \
under personality). Read across ALL of an entity's categories before \
answering, rather than jumping straight to the one category whose name \
happens to match the question.

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

Facts are grouped by concept/person/theme under a "Standing description" \
heading, then by category (e.g. technique, definition, claim), with each \
individual fact tagged by the chapter it came from, e.g. "[ch 9] pair a new \
habit with an existing one." Chapters are always listed in increasing order \
within a group. When two facts in the SAME category for the SAME entity \
describe conflicting or updated information (e.g. a claim refined or \
corrected later in the book), trust the fact from the LATER chapter as the \
current, most complete version. Facts in different categories, or about different \
specifics within a category, are NOT conflicts - treat them as \
accumulated knowledge, not contradictions to pick between.

A question about a specific kind of detail is NOT limited to the category \
whose label matches that topic - relevant details can appear under any \
category. For example, a question asking how to apply a concept should be \
answered using every relevant detail you can find, not only facts tagged \
"technique" - a fact tagged "definition" or "claim" can still describe how \
something works in practice. Read across ALL of a concept's categories \
before answering, rather than jumping straight to the one category whose \
name happens to match the question.

If the provided facts don't contain enough information to answer, say so \
plainly (e.g. "I don't have enough information about that yet") rather than \
guessing or inventing an answer."""

ANSWER_SYSTEM_PROMPTS = {"fiction": ANSWER_SYSTEM_PROMPT, "nonfiction": ANSWER_SYSTEM_PROMPT_NONFICTION}


def build_answer_user_message(question: str, context: str) -> str:
    return f"Known facts:\n{context}\n\nQuestion: {question}"
