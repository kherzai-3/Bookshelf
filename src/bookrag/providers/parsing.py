"""Shared, lenient parsing of a provider's raw text response into
ExtractedFacts. Factored out so every provider is parsed the same forgiving
way - a small local model is more likely to wrap its JSON array in an
object (e.g. {"facts": [...]}) than a well-behaved large model, but the
underlying data shape is the same either way."""

from __future__ import annotations

import json

from bookrag.providers.base import ExtractedFact, ExtractionParseError

_LIST_KEYS = ("facts", "results", "data", "items")

# The catalog's three entity kinds, matching the original brief (characters,
# settings, themes). Kept deliberately small and fixed, not just for
# tidiness: resolve_entity() matches an existing entity by (name, type)
# together, so if the same real entity gets a DIFFERENT type string across
# extraction runs (observed: a monster called "monster" in one run would
# fail to match itself if called "creature" next time), it silently becomes
# a second, duplicate entity instead of being recognized as the same one -
# entity_type drift doesn't just clutter the catalog, it breaks
# deduplication. Anything outside this list is rejected rather than let
# through, so a genuinely new category is a visible decision to make (add
# an alias below), not a silent accumulation.
ALLOWED_ENTITY_TYPES = {"character", "setting", "theme"}

# Synonyms a provider might use for one of the three real types above,
# folded in rather than accepted as their own type. monster/creature is
# confirmed from a real run (Kalkara, Wargal in Ranger's Apprentice) - both
# are non-human but still have personality/relationship/status facts, i.e.
# they're "characters" in the story sense, not a fourth kind of entity.
_ENTITY_TYPE_ALIASES = {
    "monster": "character",
    "creature": "character",
}

# The six categories the extraction prompt asks for. Unlike entity_type,
# drift here doesn't break entity deduplication - nothing else keys off
# category for identity - so an unrecognized value is folded into the
# generic "description" bucket rather than rejecting the whole fact/chapter.
# Real observed drift (llama3.2:3b, no schema enforcement): "location" and
# "author" both leaked through here before OllamaProvider started passing
# extraction_response_schema()'s enum constraint.
ALLOWED_CATEGORIES = {"personality", "appearance", "relationship", "status", "description", "development"}

# Non-fiction gets its own taxonomy rather than a parameterized version of
# the fiction one above - confirmed necessary, not just theoretically
# different, by a real checkpoint run (bookrag eval against consolidated
# Atomic Habits chapters): the fiction categories collapsed almost
# everything into "description" (a real named thing, "Habits Academy", got
# the exact same generic treatment as an abstract idea, "habits"), and
# "setting" actively produced nonsense - "desk", "phone", "bedroom",
# "coffee shop" all filed as cataloged story settings, when they were just
# illustrative examples in a discussion of habit cues. "setting" is
# dropped entirely for this reason. "concept" is the one genuinely new
# entity_type - a named, citable framework/technique the book teaches as a
# discrete unit (e.g. "The Four Laws of Behavior Change") - so
# resolve_entity's existing accumulation machinery, already proven for
# characters, pays off for a framework introduced in one place and
# elaborated later. No aliases seeded here (unlike fiction's monster/
# creature) - grown from real observed drift if/when it happens, not
# guessed upfront.
ALLOWED_ENTITY_TYPES_NONFICTION = {"character", "concept", "theme"}
_ENTITY_TYPE_ALIASES_NONFICTION: dict[str, str] = {}

# "technique" (a concrete, actionable instruction) is the single highest-
# value addition with no fiction analog - it's what lets a reader later ask
# "what techniques does this book recommend?" as a distinct question from
# "what does it claim?", the exact capability the fiction taxonomy loses
# everything worth extracting to. "relationship" is reused but redefined:
# how one concept relates to, builds on, or is a component of another, not
# person-to-person. "definition" vs "claim" has acknowledged soft edges for
# a small model (the same kind of risk that caused the fiction category
# drift above) - deliberately not resolved further until real extraction
# data shows how bad it actually is, same posture as the fiction set's own
# history.
ALLOWED_CATEGORIES_NONFICTION = {"definition", "claim", "technique", "example", "relationship", "description"}

# Which categories describe a distinct MOMENT rather than a standing property.
# This split exists because of a real, confirmed wrong answer: a character
# wounded by monsters in ch.34 and an unrelated report of his death in ch.66 -
# both `status` facts about the same entity - were fused by the answer prompt's
# "trust the later chapter" rule into "he died fighting the monsters." That rule
# is correct for a standing property (a rank, an age, a location have one
# current value, and a later chapter's version wins) and actively wrong for
# occurrences, which don't supersede each other - they both simply happened.
#
# `development` is unambiguous (the extraction prompt defines it as a notable
# action or event). `status` is defined there as a *change* in role, rank, or
# life-condition, so it's an occurrence by construction - and it's the category
# the real bug occurred in. `relationship` is the genuinely mixed one ("Halt is
# Will's master" is standing; "Halt has sworn to rescue Will" is a moment), and
# it's grouped with occurrences deliberately: mislabelling a standing fact as a
# moment only makes an answer slightly more verbose, while mislabelling a moment
# as standing reintroduces the fusion bug. Worth revisiting against real answers.
OCCURRENCE_CATEGORIES = {"status", "development", "relationship"}

# Empty for nonfiction, by design rather than omission: a definition, claim or
# technique is a standing statement about the world, and even `example` (the
# closest thing to an episode) doesn't get harmfully superseded by recency the
# way a story occurrence does. Revisit only if a real nonfiction answer shows
# the same fusion failure.
OCCURRENCE_CATEGORIES_NONFICTION: set[str] = set()

# Where a fact sits in *story* time, independent of the chapter that revealed
# it (that stays `chapter_index`, and it alone governs spoiler safety).
# Deliberately three coarse values rather than a date or an ordering: a model
# reading one chapter at a time can tell whether a sentence is set in that
# chapter's present, but it cannot place events on a global timeline, and most
# novels give no dates to place them with.
#
# Real case this exists for: `[ch 4] "King Duncan, a youth in his twenties, was
# newly crowned when Morgarath rebelled"` describes events roughly fifteen
# years before the book opens, but was stored indistinguishably from something
# happening in chapter 4 - so "how old is the King?" got answered "a youth in
# his twenties" by the recency rule. He would be about forty.
ALLOWED_WHEN = {"present", "past", "future"}
DEFAULT_WHEN = "present"

# Lenient normalization for providers that aren't schema-constrained
# (Anthropic, Fake) - same posture as the category aliases above: fold an
# obvious synonym rather than rejecting an otherwise-good fact.
_WHEN_ALIASES = {
    "now": "present",
    "current": "present",
    "currently": "present",
    "backstory": "past",
    "before": "past",
    "earlier": "past",
    "previously": "past",
    "later": "future",
    "planned": "future",
    "anticipated": "future",
}

OCCURRENCE_CATEGORIES_BY_CONTENT_TYPE = {
    "fiction": OCCURRENCE_CATEGORIES,
    "nonfiction": OCCURRENCE_CATEGORIES_NONFICTION,
}

_ENTITY_TYPES_BY_CONTENT_TYPE = {"fiction": ALLOWED_ENTITY_TYPES, "nonfiction": ALLOWED_ENTITY_TYPES_NONFICTION}
_ENTITY_TYPE_ALIASES_BY_CONTENT_TYPE = {"fiction": _ENTITY_TYPE_ALIASES, "nonfiction": _ENTITY_TYPE_ALIASES_NONFICTION}
_CATEGORIES_BY_CONTENT_TYPE = {"fiction": ALLOWED_CATEGORIES, "nonfiction": ALLOWED_CATEGORIES_NONFICTION}

# A real, observed corruption case: one response tried to emit 4 facts, but
# used typographic curly quotes ("smart quotes", “/”) for the later
# ones' JSON keys/strings instead of a real closing '"' - so json.loads()
# still succeeded (syntactically valid JSON), but 3 facts silently vanished
# into the first fact's `statement` field, which ended up containing literal
# entity_name/entity_type key text (curly-quoted, not straight-quoted - the
# check below matches the bare key name so it catches either style) from the
# swallowed objects. Dropping just that one fact (not raising, not failing
# the whole chapter) is the cheapest correct response - this is deliberately
# a defense-in-depth net, not the primary fix (see
# extraction_response_schema()'s maxLength).
_MAX_STATEMENT_LENGTH = 500
# Matches the schema cap; a phrase is a fragment ("fifteen years ago"), not a
# sentence, so anything longer is the model writing prose into the wrong field.
_MAX_TIME_PHRASE_LENGTH = 80
_SUSPICIOUS_STATEMENT_SUBSTRINGS = ("entity_name", "entity_type")


def extraction_response_schema(content_type: str = "fiction") -> dict:
    """JSON Schema for Ollama's `/api/chat` `format` field (grammar-
    constrained structured output, not just "produce some valid JSON") -
    built from ALLOWED_ENTITY_TYPES*/ALLOWED_CATEGORIES* so the schema can't
    drift from what parse_facts/​_normalize_* actually accept. Verified
    empirically against this project's local Ollama (0.33.2) to hold enum
    constraints even when the "correct" answer falls outside them - i.e.
    this is a structural guarantee, not a request the model can ignore."""
    entity_types = _ENTITY_TYPES_BY_CONTENT_TYPE[content_type]
    categories = _CATEGORIES_BY_CONTENT_TYPE[content_type]
    return {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                # A real, observed failure with no cap here: one request
                # generated 8,490+ output tokens (normal chapters produce
                # 500-1500) over 14m43s before Ollama's own server gave up
                # with a 500 and restarted - a runaway generation loop, not a
                # true hang (it was still actively generating, just never
                # satisfying the grammar's "stop" condition). An open-ended
                # array under grammar-constrained decoding has no structural
                # reason to ever close if the model doesn't confidently
                # choose to - maxItems makes "keep going forever" impossible
                # rather than just unlikely. Originally set to 25 (the
                # richest real chapter observed at the time, 32 facts, was
                # treated as an outlier); raised to 40 after a full real
                # 75-chapter extraction showed the opposite problem - 12 of
                # the last ~20 chapters landed at exactly 25, real evidence
                # the model wanted to report more and was being truncated,
                # not just capped defensively. Still a hard, finite ceiling,
                # not a return to uncapped.
                "maxItems": 40,
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": "string"},
                        "entity_type": {"type": "string", "enum": sorted(entity_types)},
                        "category": {"type": "string", "enum": sorted(categories)},
                        # Caps a runaway string before it can swallow later
                        # facts the way the corruption case above did - good
                        # real statements observed top out around 230 chars.
                        "statement": {"type": "string", "maxLength": 300},
                        # One enum token per fact, which is the whole point:
                        # deciding whether a sentence is set in the chapter's
                        # own present is a judgment a model can make from that
                        # sentence alone, unlike anything requiring a view of
                        # the whole book.
                        "when": {"type": "string", "enum": sorted(ALLOWED_WHEN)},
                        # Not required - a chapter usually gives no explicit
                        # phrase, and forcing one invites invention. Capped
                        # well under `statement` since it holds a fragment,
                        # not a sentence.
                        "time_phrase": {"type": "string", "maxLength": 80},
                    },
                    "required": ["entity_name", "entity_type", "category", "statement", "when"],
                },
            }
        },
        "required": ["facts"],
    }


def parse_facts(raw_text: str, content_type: str = "fiction") -> list[ExtractedFact]:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
    raw_text = raw_text.strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ExtractionParseError(
            f"Could not parse provider output as JSON: {raw_text[:200]!r}"
        ) from exc

    if isinstance(data, dict):
        if not data:
            return []  # {} - the model correctly reported nothing to extract
        for key in _LIST_KEYS:
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]  # a single fact object, not wrapped in a list

    if not isinstance(data, list):
        raise ExtractionParseError(f"Expected a JSON array of facts, got: {type(data).__name__}")

    facts: list[ExtractedFact] = []
    for item in data:
        try:
            entity_name = item["entity_name"]
            entity_type = item["entity_type"]
            category = item["category"]
            statement = item["statement"]
        except (KeyError, TypeError) as exc:
            raise ExtractionParseError(f"Malformed fact object in provider output: {item!r}") from exc

        if len(statement) > _MAX_STATEMENT_LENGTH or any(
            s in statement for s in _SUSPICIOUS_STATEMENT_SUBSTRINGS
        ):
            continue

        facts.append(
            ExtractedFact(
                entity_name=entity_name,
                entity_type=_normalize_entity_type(entity_type, content_type),
                category=_normalize_category(category, content_type),
                statement=statement,
                # Absent on every fact extracted before this field existed,
                # and on any provider that isn't schema-constrained and simply
                # omits it - "present" is the right reading for both.
                when=_normalize_when(item.get("when")),
                time_phrase=_normalize_time_phrase(item.get("time_phrase")),
            )
        )
    return facts


def _normalize_when(raw_when: object) -> str:
    if raw_when is None:
        return DEFAULT_WHEN
    normalized = str(raw_when).strip().lower()
    if normalized in ALLOWED_WHEN:
        return normalized
    # Unlike entity_type (which gates identity and so rejects on drift), an
    # unrecognized value here folds to the default rather than losing the
    # fact - same reasoning as `category`.
    return _WHEN_ALIASES.get(normalized, DEFAULT_WHEN)


def _normalize_time_phrase(raw_phrase: object) -> str | None:
    if raw_phrase is None:
        return None
    phrase = str(raw_phrase).strip()
    if not phrase:
        return None
    return phrase[:_MAX_TIME_PHRASE_LENGTH]


def _normalize_category(raw_category: str, content_type: str = "fiction") -> str:
    normalized = str(raw_category).strip().lower()
    allowed = _CATEGORIES_BY_CONTENT_TYPE[content_type]
    return normalized if normalized in allowed else "description"


def _normalize_entity_type(raw_type: str, content_type: str = "fiction") -> str:
    normalized = str(raw_type).strip().lower()
    allowed = _ENTITY_TYPES_BY_CONTENT_TYPE[content_type]
    aliases = _ENTITY_TYPE_ALIASES_BY_CONTENT_TYPE[content_type]
    if normalized in allowed:
        return normalized
    if normalized in aliases:
        return aliases[normalized]
    raise ExtractionParseError(
        f"Unrecognized entity_type {raw_type!r} (allowed: {sorted(allowed)}, "
        f"known aliases: {sorted(aliases)})"
    )
