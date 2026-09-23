"""Read-only harness: runs one or more provider/model combinations over the
same chapters and reports a side-by-side comparison - never writes to the real
facts.jsonl/entities.json.

**What this measures, and why these columns.** Choosing an extraction model is
not a one-number decision, and the obvious number is the misleading one. A real
measured comparison on this project's own corpus had the smaller model looking
better on the two things `summarize` used to report - it produced twice as many
facts, 18% faster - while actually being worse: those facts covered 36% *fewer*
distinct entities, thirteen times as many were near-duplicates of each other,
and it hit the schema's `maxItems` ceiling in half the chapters. It was padding,
not extracting more. Every column below exists because it was needed to see
that, and none of them needs a second model as a judge.
"""

from __future__ import annotations

import itertools
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from bookrag.ingest.chapter import Chapter
from bookrag.locate import find_passage
from bookrag.providers.base import (
    CallUsage,
    ExtractedFact,
    ExtractionParseError,
    Provider,
    last_usage,
)
from bookrag.providers.parsing import extraction_response_schema
from bookrag.storage import library_root, load_chapters, load_metadata

# Two statements counted as saying the same thing. Deliberately a crude
# content-word Jaccard rather than anything semantic: this is a *ranking*
# signal between models, not a dedup rule that decides any fact's fate, so
# being roughly right on a lot of pairs beats being exactly right on few. The
# real pipeline's own dedup is exact-match only and catches none of these.
_NEAR_DUPLICATE_SIMILARITY = 0.6
_WORD = re.compile(r"[A-Za-z0-9']+")


@dataclass
class ProviderChapterResult:
    provider_name: str
    chapter_index: int
    facts: list[ExtractedFact]
    parse_ok: bool
    # None whenever the provider cannot report it (Anthropic, the fakes) or the
    # call failed. Readers must treat None as "unknown", never as zero.
    seconds: float | None = None
    usage: CallUsage | None = None


@dataclass
class ProviderSummary:
    """One model's scorecard across every chapter it was run over."""

    provider_name: str
    chapters: int
    facts: int
    parse_failures: int
    distinct_entities: int
    quoted: int
    near_duplicate_pairs: int
    cap_hits: int
    groundedness: float
    seconds: float | None
    prompt_tokens: int | None
    output_tokens: int | None
    prompt_seconds: float | None
    samples: list[tuple[int, str]] = field(default_factory=list)

    @property
    def citation_coverage(self) -> float:
        """Share of statements the passage matcher can locate in the chapter.

        The column that protects citations. A model that paraphrases more
        loosely than the prose costs coverage silently - the facts still look
        fine, they just stop being traceable to a sentence a reader can find.
        """
        return self.quoted / self.facts if self.facts else 0.0


def max_facts_per_chapter(content_type: str = "fiction") -> int:
    """The schema's own `maxItems`, read from the schema rather than repeated.

    A chapter landing exactly on this is never a healthy result: either the
    model was truncated mid-thought or it padded to fill the budget. Counting
    those is how the padding failure becomes visible.
    """
    return extraction_response_schema(content_type)["properties"]["facts"]["maxItems"]


def run_eval(
    book_id: str,
    chapter_indices: list[int],
    providers: dict[str, Provider] | list[tuple[str, Provider]],
    root: Path | None = None,
) -> list[ProviderChapterResult]:
    """Run each (label, provider) over each chapter, in chapter order.

    `providers` is a list of (label, provider) pairs. A dict is still accepted
    - every existing caller passed one - but it cannot express two models of
    the *same* provider, which is the whole point of comparing models: keyed by
    provider name, a qwen row and a llama row collide and one silently wins.

    Chapters run in ascending order and `known_entities` accumulates across
    them, because that is what `extract_book` really does. Passing `[]` (as
    this did before) measures a first-chapter prompt for every chapter, which
    is not a condition any real run is ever in - measured, that preamble
    reaches 780 characters by chapter 8 of a real book and keeps growing.
    """
    root = root or library_root()
    chapters = {c.index: c for c in load_chapters(book_id, root)}
    content_type = load_metadata(book_id, root).get("content_type", "fiction")
    pairs = list(providers.items()) if isinstance(providers, dict) else list(providers)

    # Per provider, so each one sees the same accumulation the real pipeline
    # would give it - and so one model's entity discoveries never leak into
    # another's prompt, which would make the comparison meaningless.
    known: dict[str, list[str]] = {label: [] for label, _ in pairs}
    known_types: dict[str, dict[str, str]] = {label: {} for label, _ in pairs}

    results: list[ProviderChapterResult] = []
    for chapter_index in sorted(chapter_indices):
        chapter = chapters[chapter_index]
        for label, provider in pairs:
            started = time.monotonic()
            try:
                facts = provider.extract_facts(
                    chapter.text, known[label], content_type, known_types[label]
                )
                parse_ok = True
            except ExtractionParseError:
                facts = []
                parse_ok = False
            elapsed = time.monotonic() - started

            for fact in facts:
                if fact.entity_name not in known[label]:
                    known[label].append(fact.entity_name)
                    known_types[label][fact.entity_name] = fact.entity_type

            results.append(
                ProviderChapterResult(
                    provider_name=label,
                    chapter_index=chapter_index,
                    facts=facts,
                    parse_ok=parse_ok,
                    seconds=elapsed,
                    usage=last_usage(provider),
                )
            )
    return results


def groundedness_score(chapter_text: str, fact: ExtractedFact) -> float:
    """Cheap lexical grounding check, not a semantic judge: fraction of the
    statement's significant (>3 char) words that literally appear in the
    chapter text. A fast, deterministic sanity signal in [0.0, 1.0]."""
    words = [w.lower().strip(".,;:!?\"'") for w in fact.statement.split() if len(w) > 3]
    if not words:
        return 1.0
    text_lc = chapter_text.lower()
    grounded = sum(1 for w in words if w in text_lc)
    return grounded / len(words)


def near_duplicate_pairs(facts: list[ExtractedFact]) -> int:
    """How many pairs of statements in one chapter say the same thing.

    The failure this catches is real and invisible to everything else: a model
    reporting "was driven back into the Mountains of Rain and Night fifteen
    years ago" *and* "was exiled to the Mountains of Rain and Night fifteen
    years ago" as two facts. They are not equal strings, so the pipeline's
    exact-match dedup keeps both, and fact *count* rewards the model for it.
    """
    words = [_content_words(fact.statement) for fact in facts]
    return sum(
        1
        for a, b in itertools.combinations(words, 2)
        if a and b and len(a & b) / len(a | b) >= _NEAR_DUPLICATE_SIMILARITY
    )


def _content_words(statement: str) -> set[str]:
    return {w for w in _WORD.findall(statement.lower()) if len(w) > 3}


def summarize_results(
    results: list[ProviderChapterResult],
    chapters: dict[int, Chapter],
    content_type: str = "fiction",
    sample_count: int = 2,
) -> list[ProviderSummary]:
    """One `ProviderSummary` per model, in the order the models first appear."""
    cap = max_facts_per_chapter(content_type)
    by_provider: dict[str, list[ProviderChapterResult]] = {}
    for result in results:
        by_provider.setdefault(result.provider_name, []).append(result)

    summaries = []
    for provider_name, rows in by_provider.items():
        facts = [fact for row in rows for fact in row.facts]
        scores = [
            groundedness_score(chapters[row.chapter_index].text, fact)
            for row in rows
            for fact in row.facts
        ]
        quoted = sum(
            1
            for row in rows
            for fact in row.facts
            if find_passage(fact.statement, chapters[row.chapter_index].text) is not None
        )
        summaries.append(
            ProviderSummary(
                provider_name=provider_name,
                chapters=len(rows),
                facts=len(facts),
                parse_failures=sum(1 for row in rows if not row.parse_ok),
                distinct_entities=len({fact.entity_name for fact in facts}),
                quoted=quoted,
                near_duplicate_pairs=sum(near_duplicate_pairs(row.facts) for row in rows),
                cap_hits=sum(1 for row in rows if len(row.facts) >= cap),
                groundedness=sum(scores) / len(scores) if scores else float("nan"),
                seconds=_total(rows, lambda row: row.seconds),
                prompt_tokens=_total(rows, lambda row: _usage(row, "prompt_tokens")),
                output_tokens=_total(rows, lambda row: _usage(row, "output_tokens")),
                prompt_seconds=_total(rows, lambda row: _usage(row, "prompt_seconds")),
                samples=[
                    (row.chapter_index, " | ".join(f.statement[:60] for f in row.facts[:sample_count]))
                    for row in rows
                ],
            )
        )
    return summaries


def _usage(row: ProviderChapterResult, field_name: str):
    return getattr(row.usage, field_name, None) if row.usage else None


def _total(rows, pick):
    """Sum of a per-chapter value, or None if no chapter could report it.

    None propagates rather than being coerced to 0 so a provider that cannot
    report tokens shows a blank column instead of a confident "0 tokens".
    """
    values = [v for v in (pick(row) for row in rows) if v is not None]
    return sum(values) if values else None


def summarize(
    results: list[ProviderChapterResult],
    chapters: dict[int, Chapter],
    sample_count: int = 2,
    content_type: str = "fiction",
) -> list[str]:
    """The human-readable report, one block per model."""
    lines: list[str] = []
    cap = max_facts_per_chapter(content_type)
    for s in summarize_results(results, chapters, content_type, sample_count):
        lines.append(
            f"[{s.provider_name}] {s.facts} facts across {s.chapters} chapter(s), "
            f"{s.parse_failures} parse failure(s), avg groundedness {s.groundedness:.2f}"
        )
        lines.append(
            f"  quality: {s.distinct_entities} distinct entities, "
            f"{s.citation_coverage:.0%} citable, "
            f"{s.near_duplicate_pairs} near-duplicate pair(s), "
            f"{s.cap_hits}/{s.chapters} chapter(s) at the {cap}-fact ceiling"
        )
        if s.seconds is not None:
            cost = f"  cost: {s.seconds:.0f}s total, {s.seconds / max(1, s.chapters):.0f}s/chapter"
            if s.output_tokens is not None:
                cost += f", {s.output_tokens} output tokens"
            # Prompt *seconds*, not just prompt tokens: Ollama reuses a cached
            # KV prefix across calls that share one, so the token count can be
            # thousands while the real cost is a tenth of a second. Reporting
            # only the count would invite exactly the wrong conclusion.
            if s.prompt_tokens is not None:
                cost += f", {s.prompt_tokens} prompt tokens"
                if s.prompt_seconds is not None:
                    cost += f" ({s.prompt_seconds:.0f}s to evaluate)"
            lines.append(cost)
        for chapter_index, sample in s.samples:
            lines.append(f"  ch{chapter_index}: {sample or '(no facts)'}")
    return lines
