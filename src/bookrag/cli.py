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
from bookrag.extract.pipeline import (
    context_window_for,
    extract_book,
    resume_blocker,
    resume_start_index,
)
from bookrag.ingest import epub_loader, pdf_loader
from bookrag.ingest.chapter import Chapter
from bookrag.ingest.consolidate import consolidate_fragments, fragment_groups, should_consolidate
from bookrag.ingest.vocatives import NarratorAliases, auto_link_plan, detect_narrator_aliases
from bookrag.ingest.volumes import VolumePlan, detect_volumes, remap, volume_boundaries
from bookrag.names import person_link_groups
from bookrag.library import (
    detect_duplicate_entities,
    link_names,
    list_books,
    merge_entities,
    remove_book,
    run_doctor,
    show_book,
    split_cross_book_entity,
    unlink_names,
)
from bookrag.locate import cite_facts
from bookrag.providers.base import extraction_identity, model_placement, narrow_context_window
from bookrag.providers.registry import get_provider
from bookrag.query import facts_as_of, format_context, select_relevant_facts
from bookrag.storage import (
    incoming_root,
    library_root,
    load_chapters,
    load_declared_aliases,
    load_metadata,
    save_book,
)
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
    ingest.add_argument(
        "--no-auto-link",
        action="store_true",
        help="Report the narrator's other names without linking them (produces the unlinked baseline)",
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
    eval_cmd.add_argument(
        "--models",
        default=None,
        help=(
            "Comma-separated models to compare against each other, e.g. "
            "'qwen2.5:7b-instruct,llama3.2:3b'. Each is run over every provider in "
            "--providers, so this is the way to compare two models of the SAME provider "
            "(--model can only set one for all of them). Pulled models only - check with "
            "`ollama list`."
        ),
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

    aliases = subparsers.add_parser(
        "aliases", help="Show the names a book uses for its narrator, and link them into one character"
    )
    aliases.add_argument("book_id")
    aliases.add_argument(
        "--link",
        metavar="NAME,NAME,...",
        help="Declare these names to be one character. Run this BEFORE extract and the facts "
        "never fragment; run it after and any entities holding those names are merged.",
    )
    aliases.add_argument(
        "--auto",
        action="store_true",
        help="Apply the same automatic linking ingest does, to a book already in the library",
    )
    aliases.add_argument(
        "--unlink",
        action="store_true",
        help="Undo the declared links for this book (the entity keeps its facts; only the names are separated)",
    )

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
    if args.command == "aliases":
        return _aliases(args)
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
        sourced = loader.load_chapters_with_sources(args.path)
        metadata = loader.extract_metadata(args.path)
    except Exception as exc:
        print(f"Failed to parse {args.path}: {exc}")
        return 1

    chapters = [chapter for _source, chapter in sourced]
    chapter_sources = [source for source, _chapter in sourced]

    guessed_title, guessed_author = guess_title_author(args.path.stem)
    title = args.title or metadata.get("title") or guessed_title
    author = args.author or metadata.get("author") or guessed_author

    # Collected rather than printed as they occur. These describe the parse, so
    # they belong under a heading *after* the result line - printing them inline
    # put indented detail above the un-indented headline it was qualifying,
    # which read backwards.
    origin_notes: list[str] = []
    if not args.title and not metadata.get("title"):
        origin_notes.append(f"no title in file metadata - guessed '{title}' from filename")
    if not args.author and not metadata.get("author") and author:
        origin_notes.append(f"no author in file metadata - guessed '{author}' from filename")

    plan = detect_volumes(args.path, chapters, chapter_sources, title)

    raw_chapter_count = len(chapters)
    if should_consolidate(chapters):
        # Consolidation renumbers chapters, so a volume map made against the
        # raw fragments has to move with them - and merging must not run
        # across a volume boundary in the first place, or a chapter would
        # belong to two books at once.
        boundaries = volume_boundaries(plan)
        groups = fragment_groups(chapters, boundaries=boundaries)
        chapters = consolidate_fragments(chapters, boundaries=boundaries)
        if plan is not None:
            plan = remap(plan, groups)
        origin_notes.append(
            f"consolidated {raw_chapter_count} raw fragments into {len(chapters)} chapters"
            " (they were too small to extract well independently)"
        )

    try:
        book_id = save_book(
            args.path,
            chapters,
            title=title,
            author=author,
            series_name=args.series,
            series_position=args.series_position,
            content_type=args.content_type,
            volumes=plan.as_metadata() if plan else None,
        )
    except Exception as exc:
        # save_book rolls back its own partial book_dir on failure - nothing
        # left behind here to clean up.
        print(f"Failed to save '{title}' to the library: {exc}")
        return 1

    print(f"Ingested '{title}' as '{book_id}' ({len(chapters)} chapters)")
    if args.series:
        print(f"  series: {args.series} #{args.series_position}")

    _print_section("Parsing", origin_notes)
    _print_section("Volumes", volume_summary_lines(plan))
    _print_section("Sanity check", sanity_summary(chapters))
    found = detect_narrator_aliases(chapters)
    _print_section("Names for the narrator", narrator_alias_lines(found))
    _print_section(
        "Linked",
        auto_link_narrator(book_id, found, enabled=not args.no_auto_link)
        + auto_link_title_variants(book_id, chapters, enabled=not args.no_auto_link),
    )

    report_path = write_ingestion_report(
        book_id, chapters, raw_chapter_count=raw_chapter_count if raw_chapter_count != len(chapters) else None
    )
    files = [f"wrote {report_path}"]
    files.extend(_incoming_cleanup_notes(args.path))
    _print_section("Files", files)
    _print_section("Next steps", next_step_lines(book_id, len(chapters)))
    return 0


_VOLUMES_LISTED = 8


def volume_summary_lines(plan: VolumePlan | None) -> list[str]:
    """What the file turned out to contain, when it contains more than one
    book. Empty for the ordinary case, which is most books.

    Says it at ingest even though nothing about the ingest changed, because
    this is the one moment a reader is looking at the tool's reading of their
    file. If the detector is wrong - it can only be wrong by being *too
    eager*, since the alternative is silence - this is where they would see
    it, and the fix is to say so rather than to add a flag that turns it off.
    """
    if plan is None:
        return []
    lines = [
        f"This file holds {len(plan.volumes)} separately published books "
        f"({plan.coverage:.0%} of its text falls inside them).",
        "Ingested as one book - chapter numbers are unchanged - but a citation",
        "will name the volume and count chapters from its start, so it points at",
        "something a reader can find:",
    ]
    lines.extend(f"  {volume.label} -> {volume.title}" for volume in plan.volumes[:_VOLUMES_LISTED])
    if len(plan.volumes) > _VOLUMES_LISTED:
        lines.append(f"  ... and {len(plan.volumes) - _VOLUMES_LISTED} more")
    if plan.unlabelled_chapters:
        lines.append(
            f"{plan.unlabelled_chapters} chapters sit outside every volume (covers, a shared "
            "contents page, an about-the-author) and are cited by the file's own title"
        )
    return lines


def auto_link_narrator(book_id: str, found: NarratorAliases, enabled: bool = True) -> list[str]:
    """Link the narrator's names at the end of ingest, without asking.

    **This is what makes the detection worth running at all.** A reader's flow
    is download, drop in `data/incoming/`, ingest, extract - nothing in it goes
    near a linking command, so a feature that waits to be invoked is invisible,
    which is exactly the fault of `doctor --merge-name-variants`. An
    interactive prompt was tried and is wrong for a different reason: it needs
    a person present who can judge a book's cast, per book.

    Says what it did and how to undo it, because this is an automatic mutation
    driven by a heuristic. `auto_link_plan` is deliberately conservative and
    returns nothing for most books.
    """
    if not enabled:
        return ["skipped (--no-auto-link)"] if found.aliases else []
    names, epithets = auto_link_plan(found)
    if not names:
        return []

    result = link_names(
        book_id,
        names,
        epithets=epithets,
        reason="detected at ingest: addressed to a first-person narrator",
    )
    lines = [f"'{result.canonical_name}' also answers to {', '.join(result.aliases)}"]
    if result.epithets:
        lines.append(f"  and is referred to as {', '.join(result.epithets)}")
    lines.extend(
        [
            "  Their facts will be catalogued as one character instead of several.",
            f"  Wrong? `bookrag aliases {book_id} --unlink` undoes it, before or after extraction.",
        ]
    )
    return lines


_TITLE_GROUPS_SHOWN = 6
# Above this many forms a group is summarised by count. Set to 2 because a
# three-form group is as likely to be all sentence-initial noise ("But Lang
# Ya", "If Lang Ya", "When Lang Ya" - real output) as it is to be the
# interesting case, and there is no cheap way to tell them apart that does not
# amount to classifying the prefix, which is precisely what the residue rule
# exists to avoid.
_TITLE_FORMS_LISTED = 2


def auto_link_title_variants(book_id: str, chapters: list, enabled: bool = True) -> list[str]:
    """Link "Lord Fang Yuan" to "Fang Yuan" at ingest, without asking.

    **The third-person counterpart to `auto_link_narrator`, and it exists for
    the same reason.** `doctor --merge-name-variants` has been able to find
    these since rank 02, and a reader's flow - download, drop in
    `data/incoming/`, ingest, extract, chat - never goes near it. A link nobody
    performs is a link that never happens.

    **Why this has to run before extraction rather than after.**
    `resolve_entity` matches an incoming name against a known entity's aliases,
    so an entity that already carries "Lord Fang Yuan" when chapter 110 is
    extracted absorbs the mention instead of minting a second character. Run
    afterwards the same information only supports a merge, which is what
    `doctor` offers; run here, the fragmentation never forms.

    **The guard is different from `doctor`'s, because the evidence is.** After
    extraction there are entity types and `library` simply requires both sides
    to be characters. Here there are none, so `names.reads_as_a_person` reads
    personhood out of the prose - and the seeding path writes
    `type="character"`, so linking a place would not merely be wrong, it would
    be inert: extraction would mint its own setting entity and leave the seeded
    one an orphan.

    Announces the wait before taking it. On the longest book in the corpus the
    scan is around two minutes, and a silent two minutes mid-ingest is
    indistinguishable from a hang - the same complaint that produced
    `extract_start_notes`.
    """
    if not enabled:
        return []

    print(
        "  Reading how the book writes its characters' names "
        "(a minute or two on a long book) ...",
        flush=True,
    )
    groups = person_link_groups(chapter.text for chapter in chapters)
    if not groups:
        return []

    for group in groups:
        link_names(
            book_id,
            [group.name, *group.decorated],
            reason="detected at ingest: a decorated form of a name the book uses on its own",
        )

    # Listed only while the list stays readable. On a long book the
    # protagonist collects 33 forms, most of them sentence-initial ordinary
    # words ("But Fang Yuan", "And Fang Yuan"), which the rule links on
    # purpose and correctly - the prefix's identity never has to be decided -
    # but which read as a bug in a summary. They are harmless downstream:
    # `resolve_entity` matches an alias exactly, and
    # `query._name_matches_question` needs the whole alias to appear in the
    # question. So the count is the honest summary and `bookrag aliases` has
    # the full list.
    lines = []
    for group in groups[:_TITLE_GROUPS_SHOWN]:
        if len(group.decorated) <= _TITLE_FORMS_LISTED:
            lines.append(f"'{group.name}' also answers to {', '.join(group.decorated)}")
        else:
            lines.append(f"'{group.name}' also answers to {len(group.decorated)} other forms of that name")
    if len(groups) > _TITLE_GROUPS_SHOWN:
        lines.append(f"... and {len(groups) - _TITLE_GROUPS_SHOWN} more name(s) linked the same way")
    lines.extend(
        [
            "  Each will be catalogued as one character instead of several.",
            f"  See them all with `bookrag aliases {book_id}`.",
            f"  Wrong? `bookrag aliases {book_id} --unlink` undoes it, before or after extraction.",
        ]
    )
    return lines


def narrator_alias_lines(found: NarratorAliases) -> list[str]:
    """What the book calls its narrator, reported at ingest.

    Silent for a third-person book, which is most of them - an empty section
    prints nothing at all (see `_print_section`), so this costs those books a
    blank line and no attention. The counts are shown deliberately: they are
    what a reader needs to tell a real alias from a stray match, and on a real
    book the gap is stark (34 against 2). Each candidate is marked as a name or
    an epithet, because that distinction decides what happens to it: only names
    can be linked, and only names ever reach question matching.

    This section reports; the "Linked" section immediately after it says what
    was actually applied, and is the only authority on that. Keeping the claim
    out of here matters - a three-party scene can put a stranger's title in
    this list, so "detected" and "acted on" must not read as the same thing."""
    if not found.aliases:
        return []
    named = ", ".join(
        f"{c.name} ({c.times_addressed}x, {'name' if c.reads_as_a_name else 'epithet'})"
        for c in found.aliases
    )
    return [
        f"other characters address the narrator as: {named}",
        f"  read from dialogue in {len(found.first_person_chapters)} of "
        f"{found.chapters_considered} chapters, which are written in the first person",
        "  These are the names whose facts would otherwise be catalogued as",
        "  separate people. See 'Linked' below for what was applied.",
    ]


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
        # `bookrag eval` predates this line by a long way and was, in practice,
        # invisible: this is the one place a user is told what to do next, and
        # it sent them straight into a multi-hour commitment without mentioning
        # that the model choice behind it can be checked in a couple of
        # minutes. Changing that choice later means re-extracting the book from
        # chapter 0, so "check first" is not a nicety. Same lesson as the
        # doctor-only detectors: a capability reachable only from the README is
        # a capability nobody uses.
        "Not sure which model to use? Compare them on two chapters first,",
        "read-only and in minutes - changing model later means re-extracting:",
        f"  bookrag eval {book_id} --chapters 1,2 --models qwen2.5:7b-instruct,llama3.2:3b",
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

    # Checked before anything else, because the alternative is finding out at
    # the first chapter of a run the user expected to leave going for hours.
    # A typo'd or unpulled --model is the likeliest way to start a run that
    # cannot work, and it costs one HTTP call to rule out.
    missing = missing_model_note(provider)
    if missing:
        for line in missing:
            print(line)
        return 1

    try:
        # Kept, not just counted: unlinked_narrator_warning needs the text to
        # tell whether this book has a split character about to be baked in.
        chapters = load_chapters(args.book_id)
        chapter_count = len(chapters)
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
        for line in extract_start_notes(args.book_id, chapter_count, start_index, provider, chapters):
            print(line, flush=True)
        for line in unlinked_narrator_warning(args.book_id, chapters):
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
    # --models is the cross-product; --model stays a single override applied to
    # every provider. [None] means "whatever each provider defaults to", which
    # is what happens when neither flag is given.
    models = [m.strip() for m in args.models.split(",")] if args.models else [args.model]
    try:
        # A list of pairs, not a dict: two models of one provider have the same
        # provider name, so a dict would silently keep only the last one - the
        # exact comparison this command exists for.
        providers = [
            (_eval_label(name, model), get_provider(name, model=model))
            for name in provider_names
            for model in models
        ]
    except Exception as exc:
        print(f"Could not initialize provider(s): {exc}")
        return 1

    try:
        content_type = load_metadata(args.book_id).get("content_type", "fiction")
        results = run_eval(args.book_id, chapter_indices, providers)
        chapters = {c.index: c for c in load_chapters(args.book_id)}
    except Exception as exc:
        print(f"Eval failed: {exc}")
        return 1

    for line in summarize(results, chapters, content_type=content_type):
        print(line)
    return 0


def _eval_label(provider_name: str, model: str | None) -> str:
    """How one row is named in the report. The model is included only when the
    caller named one, so a plain `--providers ollama,fake` reads exactly as it
    did before this supported several models."""
    return f"{provider_name}:{model}" if model else provider_name


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
        used = select_relevant_facts(args.question, facts)
        print(provider.answer_question(args.question, format_context(used, content_type=content_type), content_type))
        _print_section("Sources", source_lines(used))
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
        used = select_relevant_facts(question, facts)
        print(provider.answer_question(question, format_context(used, content_type=content_type), content_type))
        _print_section("Sources", source_lines(used))


# Enough to show where an answer came from without burying the answer itself.
# An unfiltered list is not a source list, it is the fact dump rank 03 exists
# to get rid of, printed a second time with locations attached.
_SOURCES_SHOWN = 6


def source_lines(facts: list, root: Path | None = None) -> list[str]:
    """Where the facts behind an answer came from, in the reader's terms.

    **This is the whole point of the citation work**, and it is printed by
    the tool rather than asked of the model on purpose: a small local model
    asked to cite its sources invents them, and a citation that might be
    fabricated is worse than none. Everything here is computed from the
    library, so a source line is either correct or absent.

    Deduplicated by rendered location: several facts routinely come from one
    passage, and repeating the same line once per fact makes the block look
    like noise. Ordered by chapter, because a reader scanning it is asking
    "how far back does this go", not "which fact was most relevant".
    """
    if not facts:
        return []
    seen: dict[str, None] = {}
    for fact, citation in sorted(cite_facts(facts, root=root), key=lambda pair: pair[0].chapter_index):
        seen.setdefault(citation.render(), None)
    lines = list(seen)[:_SOURCES_SHOWN]
    if len(seen) > _SOURCES_SHOWN:
        lines.append(f"... and {len(seen) - _SOURCES_SHOWN} more")
    return lines


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
    if b.volumes:
        # The one place a reader can check the detector's reading of their
        # file after the fact, and the only visible sign that citations will
        # name a book the library index never lists.
        print(f"  volumes: {len(b.volumes)} separately published books stitched into this file")
        for volume in b.volumes[:_VOLUMES_LISTED]:
            print(f"    chapters {volume['start']}-{volume['end']}: {volume['title']}")
        if len(b.volumes) > _VOLUMES_LISTED:
            print(f"    ... and {len(b.volumes) - _VOLUMES_LISTED} more")
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


def _aliases(args: argparse.Namespace) -> int:
    try:
        chapters = load_chapters(args.book_id)
    except (FileNotFoundError, NotADirectoryError):
        print(f"no such book in the library: {args.book_id!r}")
        return 1

    if args.unlink:
        removed = unlink_names(args.book_id)
        if not removed:
            print(f"'{args.book_id}' has no declared links to undo.")
            return 0
        print(f"Unlinked {', '.join(removed)}.")
        print("  Already-extracted facts keep whichever entity owns them - the name alone")
        print("  is separated. Re-run `bookrag extract --restart` for a clean re-extraction.")
        return 0

    if args.link or args.auto:
        found = detect_narrator_aliases(chapters)
        if args.auto:
            lines = auto_link_narrator(args.book_id, found)
            if not lines:
                print(f"Nothing to link automatically for '{args.book_id}'.")
                print("  Auto-linking needs two names that read as proper nouns AND look like")
                print("  variants of each other. Run without --auto to see the candidates.")
                return 0
            for line in lines:
                print(line)
            return 0
        try:
            result = link_names(args.book_id, args.link.split(","), reason="named by hand")
        except ValueError as exc:
            print(f"{exc}")
            return 1
        verb = "Created" if result.created else "Updated"
        print(f"{verb} '{result.canonical_name}' with aliases: {', '.join(result.aliases) or '(none)'}")
        if result.merged_entity_ids:
            n = len(result.merged_entity_ids)
            print(f"  merged {n} existing entit{'y' if n == 1 else 'ies'} into it ({result.facts_rewritten} fact(s) rewritten)")
        if result.created:
            print("  Extraction will now resolve every one of those names to this character.")
        return 0

    declared = load_declared_aliases(args.book_id)
    if declared:
        print(f"Already linked for '{args.book_id}':")
        for group in declared:
            print(f"  names:    {', '.join(group['names'])}")
            if group["epithets"]:
                print(f"  also:     {', '.join(group['epithets'])}")
            if group["reason"]:
                print(f"  because:  {group['reason']}")
        print(f"\n  Undo with: bookrag aliases {args.book_id} --unlink\n")

    found = detect_narrator_aliases(chapters)
    if not found.aliases:
        for line in no_narrator_names_lines(args.book_id, found):
            print(line)
        return 0

    print(f"Names other characters use for the narrator of '{args.book_id}':")
    for candidate in found.aliases:
        kind = "name" if candidate.reads_as_a_name else "epithet"
        print(f"  {candidate.name:16} {candidate.times_addressed:4}x   ({kind})")
    if found.speakers:
        print()
        print("Rejected - these speak as often as they are addressed, so they are other characters:")
        for name, addressed, spoken in found.speakers:
            print(f"  {name:16} addressed {addressed}x, speaks {spoken}x")
    print()
    print(
        f"Read from {len(found.first_person_chapters)} of {found.chapters_considered} chapters"
        f" ({found.quote_style} quotes)."
    )

    names, epithets = auto_link_plan(found)
    if names and not declared:
        also = f" (and {', '.join(epithets)})" if epithets else ""
        print()
        print(f"  bookrag aliases {args.book_id} --auto   would link {', '.join(names)}{also}")
    elif not names:
        print()
        print("Nothing meets the bar for automatic linking - two names that read as proper")
        print("nouns and look like variants of each other. Link by hand with --link if you")
        print("know the book: names are matched against questions, so prefer real names.")
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


def no_narrator_names_lines(book_id: str, found: NarratorAliases) -> list[str]:
    """Why `bookrag aliases` found nothing, said in terms of what was actually
    measured instead of a claim about the book.

    This used to assert `'<book>' reads as first-person, but no name is used for
    the narrator often enough to report`, on the strength of
    `is_first_person` - which is true if **one** chapter clears the density
    gate. Measured on the corpus, that is a false statement for three of eight
    books: Reverend Insanity clears it on 1 chapter of 2,334, Atomic Habits on
    2 of 36, Moby Dick on 11 of 142. The old wording asserted the wrong thing
    about the book and then blamed the missing names on the data.

    The counts are the honest answer, so they are always printed. The sentence
    after them describes what the *pass* had to work with rather than what the
    book is - Moby Dick really is narrated by Ishmael, and only 11 of its
    chapters are first-person prose, so any wording that called it third person
    would be wrong in the other direction.
    """
    first_person, considered = len(found.first_person_chapters), found.chapters_considered
    lines = [
        f"No names found for a narrator of '{book_id}'.",
        f"  {first_person} of {considered} chapters read as first-person narration"
        + (f" ({found.quote_style} quotes)." if found.quote_style else "."),
    ]
    if not found.is_first_person:
        lines.extend(
            [
                "  This pass only works where the text says who is speaking to whom. In third",
                "  person a vocative is still findable, but nothing says who it was aimed at.",
            ]
        )
    elif not found.reads_as_first_person_throughout:
        lines.extend(
            [
                "  That is too small a share to read a narrator's names from: most chapters",
                "  carry too little first-person prose to attribute their dialogue against.",
            ]
        )
    else:
        lines.append("  No name is used for the narrator often enough to report.")
    return lines


def unlinked_narrator_warning(book_id: str, chapters: list[Chapter]) -> list[str]:
    """The last chance to catch a split character before hours of work bake it in.

    Ingest links automatically, so this is silent on the normal path - it only
    speaks when a book *has* candidates and nothing is declared, which means
    the user deliberately opted out (`ingest --no-auto-link`) or undid a link
    (`aliases --unlink`). This run is where that choice stops being cheap: the
    facts about to be written are the ones that get filed under two people.

    A warning, never a refusal. Declining to link is a legitimate answer, and
    for most books (third person, nonfiction) there is nothing to say at all.

    **Both paths that reach this line are reversibility paths**, which is how
    it shipped crashing: it unpacked `found.aliases` as `(name, count)` tuples
    long after they became `AliasCandidate` objects, so `extract` died with a
    `TypeError` for exactly the user who had just opted out or unlinked - and
    `--unlink` tells them to re-run `extract --restart`. Ingest-only tests
    never reach here, because nothing is declared *yet* at ingest time either
    way; it needs an extract *after* an unlink or a `--no-auto-link`.
    """
    if load_declared_aliases(book_id):
        return []
    found = detect_narrator_aliases(chapters)
    if not found.aliases:
        return []
    named = ", ".join(candidate.name for candidate in found.aliases[:4])
    return [
        f"  Note: this book calls its narrator {named} and nothing links them yet,",
        "  so their facts will be catalogued as separate people. Ctrl+C is safe -",
        f"  `bookrag aliases {book_id}` shows the full list.",
        "",
    ]


def missing_model_note(provider: object) -> list[str]:
    """What to tell a user whose chosen model isn't pulled - empty if it is,
    or if the provider can't say (hosted providers, the test fakes, an Ollama
    that isn't answering).

    Same optional-capability posture as `extraction_identity` and
    `model_placement`: probe a method that may not exist, and treat any
    failure as "no opinion" rather than as a problem.
    """
    probe = getattr(provider, "missing_model", None)
    if not callable(probe):
        return []
    try:
        missing = probe()
    except Exception:  # noqa: BLE001 - a preflight must never be the blocker
        return []
    if not missing:
        return []
    return [
        f"The model '{missing}' is not pulled, so this run would fail at the first chapter.",
        f"  ollama pull {missing}",
        "  (or pick another with --model; `ollama list` shows what you have)",
    ]


def extract_start_notes(
    book_id: str, chapter_count: int, start_index: int, provider: object, chapters: list | None = None
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
    notes = [headline]
    # Previewed here and applied again inside extract_book - the same
    # two-call-sites shape as resume_start_index/resume_blacker above, and for
    # the same reason: one source of truth for the policy, but the user is told
    # before the run rather than after it. narrow_context_window only ever
    # narrows, so applying it twice is a no-op the second time.
    window = _narrow_for_book(chapters, provider) if chapters else None
    if window is not None:
        notes.append(f"  context window sized to {window} tokens from this book's longest chapter")
    notes += [
        "  Expect several minutes before the first progress line: the model has to",
        "  load before chapter 1 starts, and a chapter then takes minutes on CPU.",
        "  Silence here is normal, not a hang.",
    ]
    return notes


def _narrow_for_book(chapters: list, provider: object) -> int | None:
    """The context window this book will run at, having narrowed the provider
    to it. None for a provider with no such setting."""
    ceiling = getattr(provider, "extract_num_ctx", None)
    if not isinstance(ceiling, int):
        return None
    return narrow_context_window(provider, context_window_for(chapters, ceiling=ceiling))


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
