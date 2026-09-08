"""Command-line entry point: `bookrag ingest <path>`."""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from bookrag.eval import run_eval, summarize
from bookrag.extract.pipeline import extract_book
from bookrag.ingest import epub_loader, pdf_loader
from bookrag.ingest.chapter import Chapter
from bookrag.ingest.consolidate import consolidate_fragments, should_consolidate
from bookrag.providers.registry import get_provider
from bookrag.query import facts_as_of, format_context
from bookrag.storage import incoming_root, library_root, load_chapters, load_metadata, save_book
from bookrag.titles import guess_title_author

LOADERS = {
    ".epub": epub_loader,
    ".pdf": pdf_loader,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bookrag")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest a .epub or .pdf book into the library")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--title")
    ingest.add_argument("--author")
    ingest.add_argument("--series", help="Series name, for grouping books that share continuity")
    ingest.add_argument("--series-position", type=int, help="1-indexed position within --series")
    ingest.add_argument(
        "--content-type",
        choices=["fiction", "nonfiction"],
        default="fiction",
        help="Selects the extraction category/entity taxonomy used later by 'extract' - not auto-detected",
    )

    extract = subparsers.add_parser("extract", help="Extract character/setting/theme facts for a book")
    extract.add_argument("book_id")
    extract.add_argument(
        "--provider", default=None, help="'anthropic', 'ollama', or 'fake' - defaults to $BOOKRAG_PROVIDER or 'ollama'"
    )
    extract.add_argument(
        "--model",
        default=None,
        help=(
            "Override the model for the chosen provider, e.g. 'qwen2.5:7b-instruct' (ollama) or "
            "'claude-opus-5' (anthropic). One-off override - for a persistent per-machine choice "
            "(e.g. a bigger model on a GPU box), set $OLLAMA_MODEL / $ANTHROPIC_MODEL instead "
            "(a .env file works too). Ignored for --provider fake."
        ),
    )

    eval_cmd = subparsers.add_parser("eval", help="Compare provider(s) on the same chapters, read-only")
    eval_cmd.add_argument("book_id")
    eval_cmd.add_argument("--chapters", required=True, help="Comma-separated chapter indices, e.g. 0,1,2")
    eval_cmd.add_argument("--providers", default="ollama", help="Comma-separated provider names")
    eval_cmd.add_argument(
        "--model", default=None, help="Same override as `extract --model`, applied to every provider listed"
    )

    chat = subparsers.add_parser("chat", help="Ask spoiler-safe questions about a book, up to a chapter you've read")
    chat.add_argument("book_id")
    chat.add_argument("--chapter", type=int, required=True, help="0-indexed chapter you've read up to")
    chat.add_argument(
        "--provider", default=None, help="'anthropic', 'ollama', or 'fake' - defaults to $BOOKRAG_PROVIDER or 'ollama'"
    )
    chat.add_argument("--model", default=None, help="Same override as `extract --model`")
    chat.add_argument(
        "--question", default=None, help="Ask a single question and exit, instead of starting an interactive session"
    )

    args = parser.parse_args(argv)

    if args.command == "ingest":
        return _ingest(args)
    if args.command == "extract":
        return _extract(args)
    if args.command == "eval":
        return _eval(args)
    if args.command == "chat":
        return _chat(args)
    return 1


def _ingest(args: argparse.Namespace) -> int:
    if not args.path.exists():
        print(f"File not found: {args.path}")
        return 1

    loader = LOADERS.get(args.path.suffix.lower())
    if loader is None:
        print(f"Unsupported file type: {args.path.suffix or '(none)'}")
        return 1

    if args.series and args.series_position is None:
        print("--series-position is required when --series is given")
        return 1

    try:
        chapters = loader.load_chapters(args.path)
        metadata = loader.extract_metadata(args.path)
    except Exception as exc:
        print(f"Failed to parse {args.path}: {exc}")
        return 1

    raw_chapter_count = len(chapters)
    if should_consolidate(chapters):
        chapters = consolidate_fragments(chapters)
        print(
            f"  consolidated {raw_chapter_count} raw fragments into {len(chapters)} chapters"
            " (they were too small to extract well independently)"
        )

    guessed_title, guessed_author = guess_title_author(args.path.stem)
    title = args.title or metadata.get("title") or guessed_title
    author = args.author or metadata.get("author") or guessed_author

    if not args.title and not metadata.get("title"):
        print(f"  (no title in file metadata - guessed '{title}' from filename)")
    if not args.author and not metadata.get("author") and author:
        print(f"  (no author in file metadata - guessed '{author}' from filename)")

    try:
        book_id = save_book(
            args.path,
            chapters,
            title=title,
            author=author,
            series_name=args.series,
            series_position=args.series_position,
            content_type=args.content_type,
        )
    except Exception as exc:
        # save_book rolls back its own partial book_dir on failure - nothing
        # left behind here to clean up.
        print(f"Failed to save '{title}' to the library: {exc}")
        return 1

    print(f"Ingested '{title}' as '{book_id}' ({len(chapters)} chapters)")
    if args.series:
        print(f"  series: {args.series} #{args.series_position}")
    for line in sanity_summary(chapters):
        print(line)

    report_path = write_ingestion_report(
        book_id, chapters, raw_chapter_count=raw_chapter_count if raw_chapter_count != len(chapters) else None
    )
    print(f"  wrote {report_path}")

    _remove_if_from_incoming(args.path)
    return 0


def _remove_if_from_incoming(path: Path) -> None:
    try:
        resolved = path.resolve()
        incoming = incoming_root().resolve()
    except OSError:
        return
    if incoming not in resolved.parents:
        return
    try:
        resolved.unlink()
        print(f"  removed {path.name} from data/incoming/ (safely stored in the library)")
    except OSError as exc:
        print(f"  (could not remove {path} from data/incoming/: {exc} - remove it yourself when convenient)")


def _extract(args: argparse.Namespace) -> int:
    try:
        provider = get_provider(args.provider, model=args.model)
    except Exception as exc:
        print(f"Could not initialize provider: {exc}")
        return 1

    try:
        result = extract_book(args.book_id, provider, on_chapter_done=_print_progress(time.monotonic()))
    except Exception as exc:
        print(f"Extraction failed: {exc}")
        return 1

    print(
        f"Extracted {result.fact_count} facts from {result.chapter_count} chapters "
        f"of '{result.book_id}' ({result.new_entity_count} new entities)"
    )
    if result.parse_failure_count:
        print(
            f"  {result.parse_failure_count} chapter(s) had unparseable provider output"
            " and were skipped (see entities/facts written for the rest)"
        )
    if result.ungrounded_entity_count:
        print(
            f"  {result.ungrounded_entity_count} fact(s) named a new entity that never"
            " appears in its chapter's text and were rejected as likely hallucinated"
        )
    if result.skipped_chapter_count:
        print(
            f"  {result.skipped_chapter_count} chapter(s) were too short to plausibly"
            " contain narrative content and were skipped without calling the provider"
        )
    return 0


def _eval(args: argparse.Namespace) -> int:
    try:
        chapter_indices = [int(c.strip()) for c in args.chapters.split(",")]
    except ValueError:
        print(f"Invalid --chapters value: {args.chapters!r} (expected e.g. '0,1,2')")
        return 1

    provider_names = [p.strip() for p in args.providers.split(",")]
    try:
        providers = {name: get_provider(name, model=args.model) for name in provider_names}
    except Exception as exc:
        print(f"Could not initialize provider(s): {exc}")
        return 1

    try:
        results = run_eval(args.book_id, chapter_indices, providers)
        chapters = {c.index: c for c in load_chapters(args.book_id)}
    except Exception as exc:
        print(f"Eval failed: {exc}")
        return 1

    for line in summarize(results, chapters):
        print(line)
    return 0


def _chat(args: argparse.Namespace) -> int:
    try:
        provider = get_provider(args.provider, model=args.model)
    except Exception as exc:
        print(f"Could not initialize provider: {exc}")
        return 1

    try:
        chapter_count = len(load_chapters(args.book_id))
        content_type = load_metadata(args.book_id).get("content_type", "fiction")
    except Exception as exc:
        print(f"Could not load '{args.book_id}': {exc}")
        return 1
    if not 0 <= args.chapter < chapter_count:
        print(f"Chapter {args.chapter} is out of range for '{args.book_id}' (has chapters 0-{chapter_count - 1})")
        return 1

    facts = facts_as_of(args.book_id, args.chapter)
    context = format_context(facts)

    if args.question is not None:
        print(provider.answer_question(args.question, context, content_type))
        return 0

    print(
        f"Chatting about '{args.book_id}' through chapter {args.chapter}"
        f" ({len(facts)} known fact(s)). Ctrl+D to exit."
    )
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        print(provider.answer_question(question, context, content_type))


def sanity_summary(chapters: list[Chapter], edge_count: int = 3) -> list[str]:
    """Chapter-count and title-boundary extraction is heuristic (see
    epub_loader/pdf_loader) and can silently misfire on an unusual book.
    Rather than trying to auto-detect every failure mode, surface enough for
    a human to eyeball in a few seconds and re-ingest with different options
    if something looks wrong (e.g. a title page or license text showing up
    as its own "chapter")."""
    if not chapters:
        return ["  0 chapters extracted - nothing to review."]

    word_counts = [len(c.text.split()) for c in chapters]
    lines = [
        f"  chapter length (words): min {min(word_counts)}, "
        f"median {round(statistics.median(word_counts))}, max {max(word_counts)}"
    ]

    def label(chapter: Chapter) -> str:
        return chapter.title or f"(untitled chapter {chapter.index})"

    lines.append("  first: " + " | ".join(label(c) for c in chapters[:edge_count]))
    if len(chapters) > edge_count:
        lines.append("  last: " + " | ".join(label(c) for c in chapters[-edge_count:]))
    return lines


def _print_progress(start_time: float):
    """Returns an on_chapter_done callback that prints one line per chapter
    with an elapsed/ETA estimate - a real-world need once extraction meant
    tens-to-hundreds of real LLM calls (minutes to hours), not instant
    FakeProvider calls."""

    def report(done: int, total: int) -> None:
        elapsed = time.monotonic() - start_time
        avg_per_chapter = elapsed / done
        remaining = avg_per_chapter * (total - done)
        print(
            f"  [{done}/{total}] chapter done - "
            f"elapsed {_format_duration(elapsed)}, ~{_format_duration(remaining)} remaining",
            flush=True,
        )

    return report


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes}m{seconds}s"
    if minutes:
        return f"{minutes}m{seconds}s"
    return f"{seconds}s"


def classify_ingestion(chapters: list[Chapter]) -> str:
    """"chapter-bound" if most chapters carry a real title (a heading/TOC
    signal was found); "text-bound" if extraction fell back to raw
    page/spine fragmentation with little or no title signal (see the
    epub_loader/pdf_loader "no exploitable structure" cases)."""
    if not chapters:
        return "text-bound"
    titled = sum(1 for c in chapters if c.title)
    return "chapter-bound" if titled / len(chapters) > 0.5 else "text-bound"


def write_ingestion_report(
    book_id: str, chapters: list[Chapter], root: Path | None = None, raw_chapter_count: int | None = None
) -> Path:
    """Persists the same information sanity_summary prints, plus a
    chapter-bound/text-bound classification, to data/library/<book_id>/
    ingestion_report.txt - so this is reviewable later, not just visible in
    the terminal at ingest time. `raw_chapter_count`, when given, is the
    fragment count *before* consolidate.consolidate_fragments ran - printed
    here too so this is visible on later review, not just at ingest time."""
    root = root or library_root()
    classification = classify_ingestion(chapters)
    lines = [f"book_id: {book_id}", f"classification: {classification}", *sanity_summary(chapters)]
    if raw_chapter_count is not None:
        lines.append(
            f"  consolidated {raw_chapter_count} raw fragments into {len(chapters)} chapters"
            " (they were too small to extract well independently)"
        )
    if classification == "text-bound":
        lines.append(
            "  note: no reliable chapter/heading structure was found, so the"
            " chapters above are page/spine fragments rather than real book"
            " chapters. Chapter-scoped cataloging (bookrag extract) and"
            " spoiler-safe querying (facts_as_of) still work correctly against"
            " these fragment boundaries, identified by their index - they just"
            " won't align with the book's own chapter numbers or table of"
            " contents."
        )
    report_path = root / book_id / "ingestion_report.txt"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


if __name__ == "__main__":
    raise SystemExit(main())
