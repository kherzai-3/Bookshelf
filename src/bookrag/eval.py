"""Read-only harness: runs one or more providers over the same chapters and
reports both a side-by-side human-readable comparison and an automated
groundedness score - never writes to the real facts.jsonl/entities.json."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bookrag.ingest.chapter import Chapter
from bookrag.providers.base import ExtractedFact, ExtractionParseError, Provider
from bookrag.storage import library_root, load_chapters


@dataclass
class ProviderChapterResult:
    provider_name: str
    chapter_index: int
    facts: list[ExtractedFact]
    parse_ok: bool


def run_eval(
    book_id: str,
    chapter_indices: list[int],
    providers: dict[str, Provider],
    root: Path | None = None,
) -> list[ProviderChapterResult]:
    root = root or library_root()
    chapters = {c.index: c for c in load_chapters(book_id, root)}

    results: list[ProviderChapterResult] = []
    for chapter_index in chapter_indices:
        chapter = chapters[chapter_index]
        for provider_name, provider in providers.items():
            try:
                facts = provider.extract_facts(chapter.text, [])
                parse_ok = True
            except ExtractionParseError:
                facts = []
                parse_ok = False
            results.append(ProviderChapterResult(provider_name, chapter_index, facts, parse_ok))
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


def summarize(
    results: list[ProviderChapterResult],
    chapters: dict[int, Chapter],
    sample_count: int = 2,
) -> list[str]:
    lines: list[str] = []
    by_provider: dict[str, list[ProviderChapterResult]] = {}
    for result in results:
        by_provider.setdefault(result.provider_name, []).append(result)

    for provider_name, provider_results in by_provider.items():
        total_facts = sum(len(r.facts) for r in provider_results)
        parse_failures = sum(1 for r in provider_results if not r.parse_ok)
        scores = [
            groundedness_score(chapters[r.chapter_index].text, fact)
            for r in provider_results
            for fact in r.facts
        ]
        avg_score = sum(scores) / len(scores) if scores else float("nan")
        lines.append(
            f"[{provider_name}] {total_facts} facts across {len(provider_results)} chapter(s), "
            f"{parse_failures} parse failure(s), avg groundedness {avg_score:.2f}"
        )
        for result in provider_results:
            sample = " | ".join(fact.statement[:60] for fact in result.facts[:sample_count])
            lines.append(f"  ch{result.chapter_index}: {sample or '(no facts)'}")
    return lines
