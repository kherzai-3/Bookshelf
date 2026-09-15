"""Command-line entry point: `bookrag {ingest,extract,eval,chat,list,show,remove,doctor}`."""

from __future__ import annotations

import argparse
import contextlib
import statistics
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from bookrag.eval import run_eval, summarize
from bookrag.extract.pipeline import extract_book, resume_blocker, resume_start_index
from bookrag.ingest import epub_loader, pdf_loader
from bookrag.ingest.chapter import Chapter
from bookrag.ingest.consolidate import consolidate_fragments, should_consolidate
from bookrag.library import (
    detect_duplicate_entities,
    list_books,
    merge_entities,
    remove_book,
    run_doctor,
    show_book,
    split_cross_book_entity,
)
from bookrag.providers.base import extraction_identity, model_placement
from bookrag.providers.registry import get_provider
from bookrag.query import facts_as_of, format_context, select_relevant_facts
from bookrag.storage import incoming_root, library_root, load_chapters, load_metadata, save_book
from bookrag.titles import guess_title_author

LOADERS = {
    ".epub": epub_loader,
    ".pdf": pdf_loader,
}

# Sentinel for `--log` given with no path of its own. A distinct object rather
# than a magic string, so a user who literally passes `--log "<auto>"` gets a
# file with that name instead of silently hitting the default branch.
AUTO_LOG = object()


def follow_commands(log_path: Path) -> list[str]:
    """Shell command(s) for watching `log_path` grow, for this platform.

    Windows gets both: `tail` exists under Git Bash (which is where this
    project is actually developed) but not in PowerShell or cmd, and printing
    only one of them would be wrong for roughly half the readers.
    """
    if sys.platform == "win32":
        return [
            f'tail -f "{log_path}"   (Git Bash)',
            f'Get-Content -Wait "{log_path}"   (PowerShell)',
        ]
    return [f'tail -f "{log_path}"']


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
    extract.add_argument(
        "--log",
        nargs="?",
        const=AUTO_LOG,
        default=None,
        metavar="PATH",
        help=(
            "Also write this run's output to a log file, so a multi-hour run can be "
            "backgrounded and followed with `tail -f`. With no PATH, uses "
            "<tempdir>/extract_<book_id>.log and prints where. Appends, so a resumed "
            "run continues the same log."
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
        "--split-cross-book",
        action="store_true",
        help="Split entities wrongly shared by unrelated books into one entity per book "
        "(not applied by --fix - rewrites fact records)",
    )
    doctor.add_argument(
        "--merge-name-variants",
        action="store_true",
        help="Interactively merge entities that are one person under different names, e.g. "
        "'Baron Arald' and 'Arald' (not applied by --fix - see README)",
    )
    doctor.add_argument(
        "--yes",
        action="store_true",
        help="With --merge-duplicates/--merge-name-variants, skip confirmation (keeps the most-facts entity)",
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
    # Collected rather than printed as they occur. These describe the parse, so
    # they belong under a heading *after* the result line - printing them inline
    # put indented detail above the un-indented headline it was qualifying,
    # which read backwards.
    parse_notes: list[str] = []
    if should_consolidate(chapters):
        chapters = consolidate_fragments(chapters)
        parse_notes.append(
            f"consolidated {raw_chapter_count} raw fragments into {len(chapters)} chapters"
            " (they were too small to extract well independently)"
        )

    guessed_title, guessed_author = guess_title_author(args.path.stem)
    title = args.title or metadata.get("title") or guessed_title
    author = args.author or metadata.get("author") or guessed_author

    if not args.title and not metadata.get("title"):
        parse_notes.append(f"no title in file metadata - guessed '{title}' from filename")
    if not args.author and not metadata.get("author") and author:
        parse_notes.append(f"no author in file metadata - guessed '{author}' from filename")

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

    _print_section("Parsing", parse_notes)
    _print_section("Sanity check", sanity_summary(chapters))

    report_path = write_ingestion_report(
        book_id, chapters, raw_chapter_count=raw_chapter_count if raw_chapter_count != len(chapters) else None
    )
    _print_section("Files", [f"wrote {report_path}", *_incoming_cleanup_notes(args.path)])
    _print_section("Next steps", next_step_lines(book_id, len(chapters)))
    return 0


def next_step_lines(book_id: str, chapter_count: int) -> list[str]:
    """What to run next, and how to watch it.

    Ingesting a book does not extract anything, and until this existed nothing
    printed said so - the summary ended on the ingestion report and left the
    reader to discover both the next command and the fact that it can run for
    hours. Worse, the honest way to run a job that long is to background it,
    which is precisely when a user cannot see the progress lines it prints.

    Returns lines rather than printing them, so `_print_section` owns the
    heading and the outer indent; the relative indentation here is real
    structure (a command sits under the sentence that introduces it).
    """
    return [
        f"Extract facts for '{book_id}' ({chapter_count} chapters):",
        f"  bookrag extract {book_id}",
        "",
        "A local model takes minutes per chapter, so a full-length book runs",
        "for hours. To run it in the background and follow along:",
        f"  bookrag extract {book_id} --log",
        *(f"  {line}" for line in follow_commands(default_log_path(book_id))),
        "Ctrl+C is safe - progress is saved, and re-running resumes.",
        "",
        "Or try the whole pipeline instantly, no model needed:",
        f"  bookrag extract {book_id} --provider fake",
    ]


def _incoming_cleanup_notes(path: Path) -> list[str]:
    """Deletes the staging copy under data/incoming/ and reports what happened.

    Returns notes instead of printing them so the result lands in the same
    "Files" section as the ingestion report - both are statements about what
    this command did to files on disk, and they read as one thought.
    """
    try:
        resolved = path.resolve()
        incoming = incoming_root().resolve()
    except OSError:
        return []
    if incoming not in resolved.parents:
        return []
    try:
        resolved.unlink()
        return [f"removed {path.name} from data/incoming/ (safely stored in the library)"]
    except OSError as exc:
        return [f"could not remove {path} from data/incoming/: {exc} - remove it yourself when convenient"]


def default_log_path(book_id: str) -> Path:
    """Where `--log` writes when given no path of its own.

    A predictable, per-book path matters more than a clever one: the whole
    point is that the command which starts a six-hour run and the command that
    follows it are typed at different times, often in different terminals, and
    the second one has to be guessable from the first.
    """
    return Path(tempfile.gettempdir()) / f"extract_{book_id}.log"


class _Tee:
    """Writes to a stream and a log file at once, flushing both every time.

    The flushing is the point. Python block-buffers a file, so without it a
    `tail -f` on the log shows nothing for many minutes at a stretch on a job
    whose entire purpose is watching it make progress.
    """

    def __init__(self, stream, handle) -> None:
        self._stream = stream
        self._handle = handle

    def write(self, text: str) -> int:
        written = self._stream.write(text)
        self._handle.write(text)
        self.flush()
        return written

    def flush(self) -> None:
        self._stream.flush()
        self._handle.flush()

    def isatty(self) -> bool:
        return self._stream.isatty()


def _extract(args: argparse.Namespace) -> int:
    log = getattr(args, "log", None)
    if log is None:
        return _run_extract(args)

    log_path = default_log_path(args.book_id) if log is AUTO_LOG else Path(log)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Appended, not truncated: an interrupted run is resumed with the same
        # command, and the earlier attempt's output is exactly the context you
        # want when working out why it stopped. utf-8 explicitly - a book's own
        # text reaches this file, and the platform default mangles it.
        handle = log_path.open("a", encoding="utf-8")
    except OSError as exc:
        print(f"Could not open log file {log_path}: {exc}")
        return 1

    with handle:
        handle.write(
            f"\n=== bookrag extract {args.book_id} "
            f"({datetime.now().isoformat(timespec='seconds')}) ===\n"
        )
        print(f"Logging to {log_path}")
        for line in follow_commands(log_path):
            print(f"  follow it with: {line}")
        with contextlib.redirect_stdout(_Tee(sys.stdout, handle)):
            return _run_extract(args)


def _run_extract(args: argparse.Namespace) -> int:
    try:
        provider = get_provider(args.provider, model=args.model)
    except Exception as exc:
        print(f"Could not initialize provider: {exc}")
        return 1

    try:
        chapter_count = len(load_chapters(args.book_id))
        start_index = resume_start_index(args.book_id, restart=args.restart, chapter_count=chapter_count)
        # Asked before the "Resuming..." line below, so a refusal never
        # follows an announcement that the run is under way.
        blocker = resume_blocker(args.book_id, provider, start_index=start_index)
        if blocker is not None:
            print(f"Refusing to resume '{args.book_id}': {blocker}")
            return 1
        if 0 < start_index < chapter_count:
            print(f"Resuming '{args.book_id}' from chapter {start_index}")
        # After the refusal above, never before it - see resume_blocker's
        # comment. Announcing a run that is about to be refused is exactly the
        # confusion this is meant to remove.
        for line in extract_start_notes(args.book_id, chapter_count, start_index, provider):
            print(line, flush=True)
        # Separates the banner from the progress lines that follow it at the
        # same indent, so the two don't read as one block.
        print(flush=True)
        result = extract_book(
            args.book_id,
            provider,
            on_chapter_done=_progress_and_placement(time.monotonic(), start_index, provider),
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
    # The result used to run straight on from the last of up to 75 progress
    # lines, which is exactly where it is hardest to find - especially in a
    # `--log` file read by scrolling back through hours of them.
    print()
    print(
        f"Extracted {result.fact_count} facts from {chapters_this_run} chapters "
        f"of '{result.book_id}' ({result.new_entity_count} new entities)"
    )
    # One category - what did not make it into the library - rather than four
    # loose warnings at the same indent as each other and as the result.
    # Usually empty, and an empty section prints nothing at all.
    dropped: list[str] = []
    if result.parse_failure_count:
        dropped.append(
            f"{result.parse_failure_count} chapter(s) had unparseable provider output"
            " and were skipped (see entities/facts written for the rest)"
        )
    if result.ungrounded_entity_count:
        dropped.append(
            f"{result.ungrounded_entity_count} fact(s) named a new entity that never"
            " appears in its chapter's text and were rejected as likely hallucinated"
        )
    if result.skipped_chapter_count:
        dropped.append(
            f"{result.skipped_chapter_count} chapter(s) were too short to plausibly"
            " contain narrative content and were skipped without calling the provider"
        )
    if result.duplicate_fact_count:
        dropped.append(
            f"{result.duplicate_fact_count} fact(s) exactly repeated an earlier fact"
            " in the same chapter and were dropped"
        )
    _print_section("Skipped and rejected", dropped)
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
        context = format_context(select_relevant_facts(args.question, facts), content_type=content_type)
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
        context = format_context(select_relevant_facts(question, facts), content_type=content_type)
        print(provider.answer_question(question, context, content_type))


def _list(args: argparse.Namespace) -> int:
    books = list_books()
    if not books:
        # The path is quoted in the hint because this line is read by someone
        # with an empty library, i.e. the exact person about to type a book
        # filename with an apostrophe in it for the first time.
        print('No books in the library yet - use `bookrag ingest "<path>"` to add one.')
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
        and not report.unnamed_fact_refs
        and not report.cross_book_entities
        and not report.name_variant_clusters
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
    if report.unnamed_fact_refs:
        n = len(report.unnamed_fact_refs)
        print(f"{n} entity reference(s) in facts that the registry has no record of:")
        for book_id, entity_id in report.unnamed_fact_refs:
            print(f"  - {entity_id} (in {book_id})")
        print(
            "  These facts are real content, but they render as a raw id and can't be found\n"
            "  by name. The name is unrecoverable - a fact stores only the entity_id - so\n"
            "  --fix deliberately leaves them alone. Re-extracting the affected chapters is\n"
            "  the only way to restore them."
        )
    if report.cross_book_entities:
        n = len(report.cross_book_entities)
        print(f"{n} entit{'y' if n == 1 else 'ies'} shared by unrelated books (wrongly merged identities):")
        for entity in report.cross_book_entities:
            where = ", ".join(f"{bid} ({count} facts)" for bid, count in sorted(entity.facts_per_book.items()))
            print(f"  - {entity.canonical_name} ({entity.type}): {where}")
        print(
            "  Entity identity is now scoped to a series, so no new ones form, but a\n"
            "  re-extraction resolves against this same registry and will not undo these.\n"
            "  Run `bookrag doctor --split-cross-book` to give each book its own entity."
        )
    if report.duplicate_entity_groups:
        n = len(report.duplicate_entity_groups)
        print(f"{n} possible duplicate entity cluster(s) (same name, resolved as separate entities):")
        for group in report.duplicate_entity_groups:
            label = ", ".join(f"{e.canonical_name} ({e.type}, {e.fact_count} facts)" for e in group)
            print(f"  - {label}")
    if report.name_variant_clusters:
        n = len(report.name_variant_clusters)
        print(f"{n} entit{'y' if n == 1 else 'ies'} that look like one name under several forms:")
        for cluster in report.name_variant_clusters:
            label = ", ".join(
                f"{m.canonical_name} ({m.fact_count} facts)"
                for m in sorted(cluster.members, key=lambda m: -m.fact_count)
            )
            print(f"  - {label}")
            print(f"      {'; '.join(cluster.reasons)} (in {cluster.book_id})")
        print(
            "  Merging one records every other spelling as an alias, which is what makes\n"
            "  a question about any of them find all of their facts. Run\n"
            "  `bookrag doctor --merge-name-variants` to review them one at a time."
        )

    if args.fix:
        print("Applied fixes: removed orphaned index entries, pruned stale book references, deleted fully orphaned entities.")
    elif not args.merge_duplicates and not args.split_cross_book and not args.merge_name_variants:
        print(
            "Run `bookrag doctor --fix` to apply the safe cleanups above, "
            "`bookrag doctor --merge-duplicates` to merge duplicate entity clusters, "
            "`bookrag doctor --merge-name-variants` to merge one person's several names, or "
            "`bookrag doctor --split-cross-book` to split wrongly-shared identities."
        )

    if args.split_cross_book:
        for entity in report.cross_book_entities:
            result = split_cross_book_entity(entity.entity_id)
            if result.new_entity_ids:
                print(
                    f"Split '{entity.canonical_name}' into {len(result.new_entity_ids) + 1} entities"
                    f" ({result.facts_rewritten} fact(s) rewritten)"
                )
            if result.dropped_book_ids:
                print(
                    f"  dropped {len(result.dropped_book_ids)} book reference(s) with no facts behind them:"
                    f" {', '.join(result.dropped_book_ids)}"
                )

    if args.merge_duplicates:
        aborted = _confirm_and_merge([(group, "") for group in report.duplicate_entity_groups], args.yes)
        if aborted is not None:
            return aborted

    if args.merge_name_variants:
        aborted = _confirm_and_merge(
            [(cluster.members, f"  ({'; '.join(cluster.reasons)})") for cluster in report.name_variant_clusters],
            args.yes,
        )
        if aborted is not None:
            return aborted
    return 0


def _confirm_and_merge(groups: list[tuple[list, str]], assume_yes: bool) -> int | None:
    """The per-cluster decision shared by `--merge-duplicates` and
    `--merge-name-variants`. Both end in the same question and the same
    `merge_entities` call; only the evidence differs, which is what `why`
    carries. Returns an exit code only when the run has to abort, so a caller
    can tell "finished" from "gave up".

    Both stay opt-in flags rather than part of `--fix` for the same reason:
    merging picks a winner and permanently rewrites fact ownership, which is a
    judgment call, not a cleanup."""
    for members, why in groups:
        default_keep = max(members, key=lambda e: e.fact_count)
        label = ", ".join(f"{e.canonical_name} ({e.type}, {e.fact_count} facts)" for e in members)
        if not assume_yes:
            question = (
                f"Merge [{label}] into '{default_keep.canonical_name}' "
                f"({default_keep.type}, {default_keep.fact_count} facts)? [y/N] "
            )
            try:
                answer = input(f"{why}\n{question}" if why else question).strip().lower()
            except EOFError:
                print("Aborted (no confirmation available - pass --yes to merge non-interactively).")
                return 1
            if answer != "y":
                print(f"Skipped: {label}")
                continue
        result = merge_entities([e.entity_id for e in members], keep=default_keep.entity_id)
        n = len(result.merged_entity_ids)
        print(
            f"Merged {n} entit{'y' if n == 1 else 'ies'} into '{default_keep.canonical_name}'"
            f" ({result.facts_rewritten} fact(s) rewritten)"
        )
    return None


def _print_section(header: str, lines: list[str]) -> None:
    """A titled, indented block preceded by a blank line.

    Both commands used to print everything they had to say as one dense run,
    with two-space indentation doing all the work of separation - so a reader
    could not tell where the sanity summary ended and housekeeping began, and
    `extract`'s closing result ran straight on from the last of 75 progress
    lines. Nothing here adds information; it only groups what was already said.

    **An empty section prints nothing at all**, header included, which is what
    lets callers pass a list that is usually empty (nothing was skipped, no
    parse notes) without guarding every call site. Blank lines inside a section
    are passed through unindented rather than becoming trailing whitespace.
    """
    if not lines:
        return
    print()
    print(f"{header}:")
    for line in lines:
        print(f"  {line}" if line else "")


def sanity_summary(chapters: list[Chapter], edge_count: int = 3) -> list[str]:
    """Chapter-count and title-boundary extraction is heuristic (see
    epub_loader/pdf_loader) and can silently misfire on an unusual book.
    Rather than trying to auto-detect every failure mode, surface enough for
    a human to eyeball in a few seconds and re-ingest with different options
    if something looks wrong (e.g. a title page or license text showing up
    as its own "chapter")."""
    if not chapters:
        return ["0 chapters extracted - nothing to review."]

    word_counts = [len(c.text.split()) for c in chapters]
    lines = [
        f"chapter length (words): min {min(word_counts)}, "
        f"median {round(statistics.median(word_counts))}, max {max(word_counts)}"
    ]

    def label(chapter: Chapter) -> str:
        return chapter.title or f"(untitled chapter {chapter.index})"

    lines.append("first: " + " | ".join(label(c) for c in chapters[:edge_count]))
    if len(chapters) > edge_count:
        lines.append("last: " + " | ".join(label(c) for c in chapters[-edge_count:]))
    # Returns content, not formatting - indentation belongs to whoever renders
    # it (`_print_section` on the console, `write_ingestion_report` in the file).
    return lines


def extract_start_notes(
    book_id: str, chapter_count: int, start_index: int, provider: object
) -> list[str]:
    """What this run is about to do, said *before* the first chapter instead of
    after it.

    Until this existed a fresh `bookrag extract` printed nothing at all until
    chapter 1 finished, and two slow things happen first, both silent: Ollama
    loads several GB of weights on a cold start, then the chapter itself runs
    (60s at best measured, minutes on CPU). The resulting one-to-five-minute
    silence was reported by a real user as a frozen run, which is precisely
    what it looks like from the outside.

    Nothing about the run changed - only when it says so. Printed with
    `flush=True` like the per-chapter progress, because a backgrounded run's
    stdout is block-buffered and an unflushed banner would sit in the buffer
    for minutes, reproducing the exact bug it exists to fix.
    """
    remaining = chapter_count - start_index
    identity = extraction_identity(provider)
    via = f" via {identity}" if identity else ""
    if start_index > 0:
        headline = f"Extracting {remaining} remaining chapter(s) of '{book_id}'{via}"
    else:
        headline = f"Extracting '{book_id}' - {chapter_count} chapter(s){via}"
    return [
        headline,
        "  Expect several minutes before the first progress line: the model has to",
        "  load before chapter 1 starts, and a chapter then takes minutes on CPU.",
        "  Silence here is normal, not a hang.",
    ]


def _progress_and_placement(start_time: float, start_index: int, provider: object):
    """Per-chapter progress, plus a one-time note on where the model is running.

    Reported after the *first* completed chapter rather than up front, because
    Ollama can only say where a model sits once it has actually loaded one, and
    forcing a multi-GB load before any work starts would be a worse trade than
    waiting one chapter. Chapter 1 of 75 is still early enough to act on.
    """
    progress = _print_progress(start_time, start_index)
    announced: list[bool] = []

    def report(done: int, total: int) -> None:
        progress(done, total)
        if not announced:
            announced.append(True)
            for line in placement_notes(provider):
                print(line, flush=True)

    return report


def placement_notes(provider: object) -> list[str]:
    """Lines describing GPU/CPU placement, or none if it can't be determined.

    A run that is silently CPU-bound is the expensive failure here: it looks
    identical to a fast one until hours have passed. bookrag never picks GPU or
    CPU - Ollama does, when it weighs free VRAM against the model plus its KV
    cache - so this reports rather than fixes, and points at the levers that
    actually exist.
    """
    placement = model_placement(provider)
    if placement is None:
        return []
    if placement.is_fully_on_gpu:
        return ["  model is loaded fully on the GPU"]
    if placement.is_cpu_only:
        return [
            "  NOTE: this run is on CPU only - no part of the model is on a GPU.",
            "  Expect hours for a full-length book. If this machine has a supported",
            "  GPU, check `ollama ps` and its driver; otherwise $OLLAMA_BASE_URL can",
            "  point bookrag at another machine that has one.",
        ]
    percent = round(100 * placement.gpu_fraction)
    return [
        f"  NOTE: only {percent}% of the model is on the GPU; the rest is on CPU.",
        "  Partial offload runs much closer to CPU speed than GPU speed, since the",
        "  CPU-resident layers gate every token. Freeing VRAM may fit the rest: a",
        "  lower $OLLAMA_NUM_CTX, or a smaller/more-quantized model.",
    ]


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
    # sanity_summary returns unindented content; the report indents it under
    # its own two header lines, the same way _print_section does on the console.
    lines = [
        f"book_id: {book_id}",
        f"classification: {classification}",
        *(f"  {line}" for line in sanity_summary(chapters)),
    ]
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
