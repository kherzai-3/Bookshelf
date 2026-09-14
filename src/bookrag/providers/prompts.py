"""Shared prompts - every provider is given the same instructions for a
given task, so the eval harness compares providers/models, not incidental
differences in prompt wording."""

from __future__ import annotations

EXTRACTION_SYSTEM_PROMPT = """You extract structured facts about characters, settings, \
and themes from a single chapter of a novel.

Respond with ONLY a JSON object of the shape {"facts": [...]}, no prose, no \
markdown fences. Each element of "facts" is:
{"entity_name": str, "entity_type": "character"|"setting"|"theme",
 "category": str, "statement": str, "when": "present"|"past"|"future",
 "time_phrase": str (optional)}

"when" says WHEN THE THING HAPPENED in the story, which is not the same as \
which chapter you read it in. Judge it from the sentence itself:
- present: it is happening now, in this chapter's scene. Most facts are this.
- past: the text is recounting something that already happened - a memory, a \
character explaining history, a reference to an earlier war or an upbringing. \
This includes events from long before the book began, which is exactly why \
the field exists: without it, "the King was newly crowned when the rebellion \
came" reads as though he were newly crowned right now.
- future: something planned, intended, promised, or predicted, which has not \
happened yet.

"time_phrase" is the text's OWN words for when it happened - "fifteen years \
ago", "the next morning", "before the rebellion" - copied exactly. Include it \
only when the chapter actually states one. Leave it out otherwise; never \
estimate, calculate, or invent a time.

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
life-condition (e.g. "became the archivist's apprentice", "was accepted into \
the academy", "is now the captain of the guard") - reserve this for milestone \
changes, not fleeting reactions or feelings.
- description: a general fact about a setting or theme, or anything that \
doesn't fit the other categories.
- development: a notable action, decision, or event involving the entity \
that doesn't itself change their status.

Every statement must be self-contained and understandable on its own, \
without needing the surrounding chapter text - name the entity or clearly \
state what happened, rather than a bare pronoun with no context (write \
"Lira felt nervous about the trial" rather than "she knew it all too \
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
under only one (e.g. "he scratched his close-cropped white beard \
thoughtfully" is BOTH an appearance detail - he has a close-cropped white \
beard - AND a personality/mood cue - he was being thoughtful; report both, \
don't pick just one).

Only report something if it is directly and explicitly stated or shown in \
the chapter text below - never invent a detail, and never introduce an \
entity whose name doesn't appear in the text. If this chapter's text is not \
part of the story's narrative (e.g. a copyright notice, dedication, table \
of contents, or author biography), or if nothing about a character, \
setting, or theme is revealed, return {"facts": []}.

The example below is an ILLUSTRATION OF THE OUTPUT FORMAT ONLY. It is not \
part of the book you are reading, and its invented names (Lira, Marek) and \
details must never appear in your output. Extract only from the chapter \
text you are actually given.

Example:
Chapter text: "Lira climbed the last of the steps, breathing hard. Marek \
handed her the iron key without a word - the mark of a full keeper of the \
archive. Lira's hands shook as she took it. Marek scratched his \
close-cropped white beard thoughtfully, his long canvas coat already dusted \
with ash as he turned away. He had earned his own key thirty years earlier, \
during the siege, and he meant to leave for the coast at dawn."

{"facts": [
  {"entity_name": "Lira", "entity_type": "character", "category": "status", \
"statement": "Lira received the iron key from Marek, marking her as a full \
keeper of the archive.", "when": "present"},
  {"entity_name": "Lira", "entity_type": "character", "category": \
"personality", "statement": "Lira's hands shook with emotion as she \
received the key.", "when": "present"},
  {"entity_name": "Marek", "entity_type": "character", "category": \
"appearance", "statement": "Marek has a close-cropped white beard.", \
"when": "present"},
  {"entity_name": "Marek", "entity_type": "character", "category": \
"personality", "statement": "Marek scratched his beard thoughtfully.", \
"when": "present"},
  {"entity_name": "Marek", "entity_type": "character", "category": \
"appearance", "statement": "Marek wears a long canvas coat dusted with \
ash.", "when": "present"},
  {"entity_name": "Marek", "entity_type": "character", "category": \
"status", "statement": "Marek earned his keeper's key during the siege.", \
"when": "past", "time_phrase": "thirty years earlier"},
  {"entity_name": "Marek", "entity_type": "character", "category": \
"development", "statement": "Marek intended to leave for the coast.", \
"when": "future", "time_phrase": "at dawn"}
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
 "category": str, "statement": str, "when": "present"|"past"|"future",
 "time_phrase": str (optional)}

Use "when": "present" for anything the book states as being the case - a \
definition, a claim, a technique. That is almost everything. Use "past" only \
for a historical anecdote or case study describing something that already \
happened ("in 1954, a runner broke the four-minute mile"), and "future" for a \
prediction about what will happen. "time_phrase" is the book's own wording \
for the date or period, copied exactly, and only when it states one - never \
estimated or invented.

category must be one of:
- definition: what a concept or technique fundamentally is, in the \
author's own terms (e.g. "deliberate practice is training aimed at a \
specific weakness rather than general repetition").
- claim: an assertion about cause and effect, human behavior, or the \
world - not itself an instruction to act.
- technique: a concrete, actionable instruction the reader is told to do \
(e.g. "write down the single hardest step before starting").
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

The example below is an ILLUSTRATION OF THE OUTPUT FORMAT ONLY. It is not \
part of the book you are reading, and its invented names (Anchoring, Sam \
Ortiz) and details must never appear in your output. Extract only from the \
chapter text you are actually given.

Example:
Chapter text: "One of the most reliable ways to start a new routine is to \
attach it to something you already do every day - a technique this book \
calls anchoring. Sam Ortiz, a reader who wrote in, attached ten minutes of \
reading to his after-dinner coffee two years ago and has not missed a night \
since."

{"facts": [
  {"entity_name": "Anchoring", "entity_type": "concept", "category": \
"technique", "statement": "Attach a new routine to something you already do \
every day, performing the new routine immediately after the existing one.", \
"when": "present"},
  {"entity_name": "Sam Ortiz", "entity_type": "character", "category": \
"example", "statement": "Sam Ortiz attached ten minutes of reading to his \
after-dinner coffee and has kept the routine every night since.", "when": \
"past", "time_phrase": "two years ago"}
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
tagged by the chapter it came from, e.g. "[ch 9] was promoted to captain of \
the guard." Chapters are always listed in increasing order. Within each entity the \
facts are split into up to four sections under their own headings, and each \
section must be read DIFFERENTLY. A rule stated for one section NEVER \
applies to another:

- Lines under "What happened, in order" are SEPARATE MOMENTS in the story. A \
later line never corrects, replaces, or concludes an earlier one - both \
things simply happened, at different times. Never merge two of these into a \
single claim, and never assume one caused or resolved the other unless a \
fact explicitly says so. Two entries that sound contradictory are usually \
two different occasions, not a correction. If the reader asks what happened \
to someone, walk through the sequence rather than picking one line.
- Lines under "Standing description" describe how something simply IS. Here, \
and ONLY here, when two lines in the same category genuinely conflict (a \
rank, an age, a location can only have one current value), trust the LATER \
chapter as the current state - an earlier one can simply be outdated. Never \
apply this rule to a line from any other section, and never treat a single \
lone fact as "the latest known state" - one fact is not a sequence, it is \
just that section's only entry.
- Lines under "Background" describe things that happened BEFORE the story's \
present, often long before the book opens, even though the reader learned \
them in the chapter shown. Never present a Background line as someone's \
current situation, and never let one override or be overridden by a line \
from another section - "was newly crowned when the rebellion came" describes \
a man as he was years ago, not as he is now. If a question asks how someone \
is at present, answer from the other sections and use Background only to \
explain how they got there. **If Background is the only place the facts \
describe some attribute of a person - their age, rank, health, location - \
then the facts DO NOT say what it is now. Say so: report what the Background \
line describes, state plainly that it describes an earlier time, and say the \
book has not told you the present value. Do not fill the gap by carrying the \
old value forward.**
- Lines under "Expected or planned" had NOT happened yet as of the chapter \
shown. Never report one as something that has already occurred.

Some lines carry the book's own wording for when something happened, after \
the chapter tag - "[ch 12 - fifteen years earlier]". Use that wording as-is \
if it helps; do not try to convert it into a date or calculate from it.

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
individual fact tagged by the chapter it came from, e.g. "[ch 9] write down \
the single hardest step before starting." Chapters are always listed in increasing order \
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
