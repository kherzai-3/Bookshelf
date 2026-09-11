"""Command-line entry point: `bookrag {ingest,extract,eval,chat,list,show,remove,doctor}`."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

from bookrag.eval import run_eval, summarize
from bookrag.extract.pipeline import extract_book, resume_start_index
from bookrag.ingest import epub_loader, pdf_loader
from bookrag.ingest.chapter import Chapter
from bookrag.ingest.consolidate import consolidate_fragments, should_consolidate
from bookrag.library import detect_duplicate_entities, list_books, merge_entities, remove_book, run_doctor, show_book
from bookrag.providers.registry import get_provider
from bookrag.query import facts_as_of, format_context, select_relevant_facts
from bookrag.storage import incoming_root, library_root, load_chapters, load_metadata, save_book
from bookrag.titles import guess_title_author

LOADERS = {
    ".epub": epub_loader,
    ".pdf": pdf_loader,
}


def _use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr. Real book text is full of curly quotes and
    dashes (U+2019 etc.), but a Windows console defaults to a legacy code page
    (cp1252 observed here) that can't represent them - so correctly-stored
    facts printed by `chat` came out as mojibake ("Ranger�s cloak"), making
    clean data look like a corrupted extraction. This is a display fix only;
    nothing about what's stored changes. Guarded because a replaced stream
    (pytest's capture, a StringIO) may not implement reconfigure()."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _use_utf8_output()
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
    extract.add_argument(
        "--restart",
        action="store_true",
        help="Ignore any saved progress and re-extract from chapter 0, overwriting facts.jsonl",
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

    subparsers.add_parser("list", help="List every book in the library and its extraction status")

    show = subparsers.add_parser("show", help="Show details for one book in the library")
    show.add_argument("book_id")

    remove = subparsers.add_parser("remove", help="Delete a book from the library (and its entity references)")
    remove.add_argument("book_id")
    remove.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")

    doctor = subparsers.add_parser("doctor", help="Check the library for consistency issues (read-only by default)")
    doctor.add_argument("--fix", action="store_true", help="Apply the safe, obvious cleanups instead of just reporting")
    doctor.add_argument(
        "--merge-duplicates",
        action="store_true",
        help="Interactively merge detected duplicate-entity clusters (not applied by --fix - see README)",
    )
    doctor.add_argument(
        "--yes", action="store_true", help="With --merge-duplicates, skip confirmation (keeps the most-facts entity)"
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
    if args.command == "list":
        return _list(args)
    if args.command == "show":
        return _show(args)
    if args.command == "remove":
        return _remove(args)
    if args.command == "doctor":
        return _doctor(args)
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
        chapter_count = len(load_chapters(args.book_id))
        start_index = resume_start_index(args.book_id, restart=args.restart, chapter_count=chapter_count)
        if 0 < start_index < chapter_count:
            print(f"Resuming '{args.book_id}' from chapter {start_index}")
        result = extract_book(
            args.book_id,
            provider,
            on_chapter_done=_print_progress(time.monotonic(), start_index),
            restart=args.restart,
        )
    except KeyboardInterrupt:
        print()
        print("Interrupted - progress has been saved. Run this command again to resume from where it left off.")
        return 1
    except Exception as exc:
        print(f"Extraction failed: {exc}")
        return 1

    if result.already_complete:
        print(f"'{result.book_id}' is already fully extracted ({result.chapter_count} chapters) - nothing to do.")
        print("  pass --restart to re-extract from scratch")
        return 0

    chapters_this_run = result.chapter_count - (result.resumed_from_chapter or 0)
    print(
        f"Extracted {result.fact_count} facts from {chapters_this_run} chapters "
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
    if result.duplicate_fact_count:
        print(
            f"  {result.duplicate_fact_count} fact(s) exactly repeated an earlier fact"
            " in the same chapter and were dropped"
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

    if args.question is not None:
        context = format_context(select_relevant_facts(args.question, facts))
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
        # Recomputed every question, not once up front - retrieval is
        # question-dependent (see query.select_relevant_facts), so a fixed
        # context built before the first question was ever typed can't
        # reflect it.
        context = format_context(select_relevant_facts(question, facts))
        print(provider.answer_question(question, context, content_type))


def _list(args: argparse.Namespace) -> int:
    books = list_books()
    if not books:
        print("No books in the library yet - use `bookrag ingest <path>` to add one.")
        return 0

    headers = ["book_id", "title", "author", "chapters", "type", "facts", "series"]
    rows = []
    for b in books:
        if b.orphaned:
            rows.append([b.book_id, b.title, b.author or "-", "?", "?", "ORPHANED (see `bookrag doctor`)", "-"])
            continue
        facts_col = "-"
        if b.fact_count is not None:
            facts_col = str(b.fact_count)
            if b.partial:
                facts_col += f" (partial: {b.chapters_extracted}/{b.chapter_count} ch)"
        series_col = f"{b.series['name']} #{b.series['position']}" if b.series else "-"
        rows.append(
            [b.book_id, b.title, b.author or "-", str(b.chapter_count), b.content_type, facts_col, series_col]
        )

    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]

    def fmt(cells: list[str]) -> str:
        return "  ".join(cell.ljust(w) for cell, w in zip(cells, widths))

    print(fmt(headers))
    print(fmt(["-" * w for w in widths]))
    for row in rows:
        print(fmt(row))
    return 0


def _show(args: argparse.Namespace) -> int:
    try:
        b = show_book(args.book_id)
    except ValueError as exc:
        print(str(exc))
        return 1

    if b.orphaned:
        print(f"'{b.book_id}' is listed in the library index but its directory is missing or incomplete.")
        print("Run `bookrag doctor --fix` to clean up the stale index entry.")
        return 1

    print(b.title + (f" by {b.author}" if b.author else ""))
    print(f"  book_id: {b.book_id}")
    print(f"  content_type: {b.content_type}")
    print(f"  chapters: {b.chapter_count}")
    if b.series:
        print(f"  series: {b.series['name']} #{b.series['position']}")
    if b.fact_count is None:
        print(f"  extraction: not yet extracted (bookrag extract {b.book_id})")
    else:
        status = (
            f"partially extracted ({b.chapters_extracted}/{b.chapter_count} chapters)"
            if b.partial
            else "fully extracted"
        )
        print(f"  extraction: {status} - {b.fact_count} facts, {b.entity_count} entities")
    return 0


def _remove(args: argparse.Namespace) -> int:
    try:
        label = show_book(args.book_id).title
    except ValueError:
        if not (library_root() / args.book_id).exists():
            print(f"no such book in the library: {args.book_id!r}")
            return 1
        label = args.book_id

    if not args.yes:
        try:
            answer = input(
                f"Remove '{label}' ({args.book_id}) from the library? This deletes its chapters/facts"
                " permanently. [y/N] "
            ).strip().lower()
        except EOFError:
            print("Aborted (no confirmation available - pass --yes to remove non-interactively).")
            return 1
        if answer != "y":
            print("Aborted.")
            return 1

    result = remove_book(args.book_id)
    print(f"Removed '{args.book_id}' from the library.")
    if result.entities_pruned:
        note = f"  pruned {args.book_id} from {result.entities_pruned} entit{'y' if result.entities_pruned == 1 else 'ies'}"
        if result.entities_deleted:
            note += f", deleted {result.entities_deleted} that became fully orphaned"
        print(note)
    return 0


def _doctor(args: argparse.Namespace) -> int:
    report = run_doctor(fix=args.fix)

    nothing_found = (
        not report.orphaned_index_entries
        and not report.stale_entity_book_refs
        and not report.orphaned_entities
        and not report.duplicate_entity_groups
    )
    if nothing_found:
        print("Library is consistent - no issues found.")
        return 0

    if report.orphaned_index_entries:
        n = len(report.orphaned_index_entries)
        print(f"{n} orphaned index entr{'y' if n == 1 else 'ies'} (directory missing):")
        for book_id in report.orphaned_index_entries:
            print(f"  - {book_id}")
    if report.stale_entity_book_refs:
        n = len(report.stale_entity_book_refs)
        print(f"{n} stale entity->book reference(s) (book no longer exists):")
        for entity_id, book_id in report.stale_entity_book_refs:
            print(f"  - {entity_id} -> {book_id}")
    if report.orphaned_entities:
        n = len(report.orphaned_entities)
        print(f"{n} orphaned entit{'y' if n == 1 else 'ies'} (zero facts reference them in any existing book):")
        for entity_id in report.orphaned_entities:
            print(f"  - {entity_id}")
    if report.duplicate_entity_groups:
        n = len(report.duplicate_entity_groups)
        print(f"{n} possible duplicate entity cluster(s) (same name, resolved as separate entities):")
        for group in report.duplicate_entity_groups:
            label = ", ".join(f"{e.canonical_name} ({e.type}, {e.fact_count} facts)" for e in group)
            print(f"  - {label}")

    if args.fix:
        print("Applied fixes: removed orphaned index entries, pruned stale book references, deleted fully orphaned entities.")
    elif not args.merge_duplicates:
        print(
            "Run `bookrag doctor --fix` to apply the safe cleanups above, or "
            "`bookrag doctor --merge-duplicates` to merge duplicate entity clusters."
        )

    if args.merge_duplicates:
        for group in report.duplicate_entity_groups:
            default_keep = max(group, key=lambda e: e.fact_count)
            label = ", ".join(f"{e.canonical_name} ({e.type}, {e.fact_count} facts)" for e in group)
            if not args.yes:
                try:
                    answer = (
                        input(
                            f"Merge [{label}] into '{default_keep.canonical_name}' "
                            f"({default_keep.type}, {default_keep.fact_count} facts)? [y/N] "
                        )
                        .strip()
                        .lower()
                    )
                except EOFError:
                    print("Aborted (no confirmation available - pass --yes to merge non-interactively).")
                    return 1
                if answer != "y":
                    print(f"Skipped: {label}")
                    continue
            result = merge_entities([e.entity_id for e in group], keep=default_keep.entity_id)
            n = len(result.merged_entity_ids)
            print(
                f"Merged {n} entit{'y' if n == 1 else 'ies'} into '{default_keep.canonical_name}'"
                f" ({result.facts_rewritten} fact(s) rewritten)"
            )
    return 0


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


def _print_progress(start_time: float, start_index: int = 0):
    """Returns an on_chapter_done callback that prints one line per chapter
    with an elapsed/ETA estimate - a real-world need once extraction meant
    tens-to-hundreds of real LLM calls (minutes to hours), not instant
    FakeProvider calls.

    `start_index` matters on a resumed run: `done` is the *absolute* chapter
    position (it starts at start_index + 1), but `start_time` only covers the
    chapters this run actually processed. Dividing by `done` would credit the
    elapsed time to chapters an earlier run paid for, understating the
    per-chapter average and so the estimate - real case: a resume from chapter
    11 of 75 divided by 56 instead of 45, reporting ~60 min left when the
    honest figure was ~75."""

    def report(done: int, total: int) -> None:
        elapsed = time.monotonic() - start_time
        processed = max(done - start_index, 1)
        avg_per_chapter = elapsed / processed
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
