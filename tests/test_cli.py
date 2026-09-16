import io
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

from bookrag.cli import (
    _print_progress,
    _print_section,
    _Tee,
    _use_utf8_output,
    default_log_path,
    extract_start_notes,
    main,
    narrator_alias_lines,
)
from bookrag.extract.resolve import load_entities, save_entities
from bookrag.ingest.vocatives import AliasCandidate, NarratorAliases
from bookrag.storage import load_chapters
from tests.helpers import (
    build_first_person_epub,
    build_fragmented_epub,
    build_narrative_epub,
    build_sample_epub,
)


@pytest.fixture(autouse=True)
def _library_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "library"
    monkeypatch.setenv("BOOKRAG_LIBRARY_ROOT", str(root))
    return root


def test_ingest_epub_end_to_end(tmp_path: Path, _library_root: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    exit_code = main(["ingest", str(epub_path)])

    assert exit_code == 0
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    metadata = json.loads((book_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["title"] == "Test Book"
    assert metadata["author"] == "Test Author"
    assert metadata["chapter_count"] == 2
    assert (book_dir / "source.epub").exists()


def test_ingest_consolidates_many_small_fragments(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "fragmented.epub"
    build_fragmented_epub(epub_path, fragment_count=40, words_per_fragment=100)  # 4000 words total

    exit_code = main(["ingest", str(epub_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "consolidated 40 raw fragments into" in output
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    metadata = json.loads((book_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["chapter_count"] < 40
    report = (book_dir / "ingestion_report.txt").read_text(encoding="utf-8")
    assert "consolidated 40 raw fragments into" in report


def test_ingest_defaults_to_fiction_content_type(tmp_path: Path, _library_root: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    exit_code = main(["ingest", str(epub_path)])

    assert exit_code == 0
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    metadata = json.loads((book_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["content_type"] == "fiction"


def test_ingest_with_explicit_content_type(tmp_path: Path, _library_root: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    exit_code = main(["ingest", str(epub_path), "--content-type", "nonfiction"])

    assert exit_code == 0
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    metadata = json.loads((book_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["content_type"] == "nonfiction"


def test_ingest_with_series_flags(tmp_path: Path, _library_root: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    exit_code = main(
        ["ingest", str(epub_path), "--series", "The Saga", "--series-position", "1"]
    )

    assert exit_code == 0
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    metadata = json.loads((book_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["series"] == {"name": "The Saga", "position": 1}


def test_ingest_series_without_position_is_rejected(tmp_path: Path, _library_root: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    exit_code = main(["ingest", str(epub_path), "--series", "The Saga"])

    assert exit_code == 1
    assert not _library_root.exists()  # rejected before save_book ever ran


def test_ingest_missing_file(tmp_path: Path, _library_root: Path) -> None:
    exit_code = main(["ingest", str(tmp_path / "missing.epub")])

    assert exit_code == 1


def test_ingest_unsupported_extension(tmp_path: Path, _library_root: Path) -> None:
    bogus = tmp_path / "notes.txt"
    bogus.write_text("not a book", encoding="utf-8")

    exit_code = main(["ingest", str(bogus)])

    assert exit_code == 1


def test_ingest_corrupt_epub_fails_cleanly_instead_of_crashing(
    tmp_path: Path, _library_root: Path
) -> None:
    corrupt = tmp_path / "corrupt.epub"
    corrupt.write_bytes(b"this is not a real epub/zip file")

    exit_code = main(["ingest", str(corrupt)])

    assert exit_code == 1
    assert not _library_root.exists()  # save_book never ran; nothing left behind


def test_ingest_writes_an_ingestion_report(tmp_path: Path, _library_root: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    exit_code = main(["ingest", str(epub_path)])

    assert exit_code == 0
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    report = (book_dir / "ingestion_report.txt").read_text(encoding="utf-8")
    assert "classification: chapter-bound" in report


def test_ingest_deletes_source_from_incoming_on_success(
    tmp_path: Path, _library_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    monkeypatch.setenv("BOOKRAG_INCOMING_ROOT", str(incoming))
    epub_path = incoming / "sample.epub"
    build_sample_epub(epub_path)

    exit_code = main(["ingest", str(epub_path)])

    assert exit_code == 0
    assert not epub_path.exists()


def test_ingest_does_not_delete_source_outside_incoming(
    tmp_path: Path, _library_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    monkeypatch.setenv("BOOKRAG_INCOMING_ROOT", str(incoming))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    epub_path = elsewhere / "sample.epub"
    build_sample_epub(epub_path)

    exit_code = main(["ingest", str(epub_path)])

    assert exit_code == 0
    assert epub_path.exists()


def test_extract_passes_model_override_to_get_provider(
    tmp_path: Path, _library_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    calls: list[tuple[str | None, str | None]] = []

    def fake_get_provider(name: str | None = None, model: str | None = None):
        calls.append((name, model))
        from bookrag.providers.fake_provider import FakeProvider

        return FakeProvider()

    monkeypatch.setattr("bookrag.cli.get_provider", fake_get_provider)

    exit_code = main(["extract", book_dir.name, "--provider", "fake", "--model", "qwen2.5:7b-instruct"])

    assert exit_code == 0
    assert calls == [("fake", "qwen2.5:7b-instruct")]


def test_extract_with_fake_provider(tmp_path: Path, _library_root: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    exit_code = main(["extract", book_dir.name, "--provider", "fake"])

    assert exit_code == 0
    assert (book_dir / "facts.jsonl").exists()
    assert (_library_root / "entities.json").exists()


def test_extract_prints_per_chapter_progress(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    main(["extract", book_dir.name, "--provider", "fake"])

    output = capsys.readouterr().out
    assert "[1/2] chapter done - elapsed" in output
    assert "[2/2] chapter done - elapsed" in output
    assert "remaining" in output


def test_progress_estimate_ignores_chapters_an_earlier_run_already_did(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`done` is the *absolute* chapter position, but the timer only covers the
    chapters this run processed - so a resumed run must divide by the latter.
    Real case: resuming at chapter 11 of 75 divided elapsed time by 56 instead
    of 45, crediting time to chapters an earlier run paid for and reporting
    ~60 minutes left when the honest figure was ~75."""
    report = _print_progress(time.monotonic() - 100.0, start_index=10)

    report(20, 30)

    output = capsys.readouterr().out
    # 100s spread over the 10 chapters this run actually did = 10s each, and
    # 10 chapters remain -> 100s, not the 150s a divide-by-20 would report.
    assert "[20/30] chapter done" in output
    assert "1m40s remaining" in output


def test_progress_estimate_on_a_fresh_run_counts_every_completed_chapter(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The companion case: with no resume, every completed chapter does belong
    to this run, so the average is unchanged from the original behaviour."""
    report = _print_progress(time.monotonic() - 100.0)

    report(10, 30)

    output = capsys.readouterr().out
    # 100s over 10 chapters = 10s each, 20 remaining -> 200s.
    assert "3m20s remaining" in output


def test_utf8_output_setup_tolerates_a_stream_that_cannot_be_reconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anything that swaps sys.stdout for a plain object (pytest's own capture,
    a StringIO) leaves a stream with no reconfigure() - forcing UTF-8 must
    degrade quietly there rather than crashing every command."""
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    _use_utf8_output()


def test_extract_is_a_no_op_on_an_already_extracted_book(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])
    capsys.readouterr()  # discard the first run's output

    exit_code = main(["extract", book_dir.name, "--provider", "fake"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "already fully extracted" in output
    assert "--restart" in output


def test_extract_restart_reextracts_an_already_extracted_book(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])
    capsys.readouterr()

    exit_code = main(["extract", book_dir.name, "--provider", "fake", "--restart"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "already fully extracted" not in output
    assert "Extracted" in output


def test_extract_prints_a_resuming_message_after_an_interruption(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    # Simulate a crash after chapter 0 by writing progress directly, the
    # same state a real interrupted extract_book run would leave behind.
    chapter_count = len(load_chapters(book_dir.name))
    (book_dir / "extraction_progress.json").write_text(
        json.dumps({"chapter_count": chapter_count, "next_chapter_index": 1}), encoding="utf-8"
    )
    (book_dir / "facts.jsonl").write_text("", encoding="utf-8")

    exit_code = main(["extract", book_dir.name, "--provider", "fake"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"Resuming '{book_dir.name}' from chapter 1" in output


def test_extract_announces_the_run_before_the_first_chapter_completes(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A real user reported a fresh extract as a frozen run. It wasn't: nothing
    was printed until chapter 1 finished, and on a cold start that is a model
    load plus a full chapter of inference - one to five minutes of silence.

    The banner has to come out *before* the first per-chapter progress line, so
    assert on the ordering rather than merely on its presence."""
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    capsys.readouterr()  # discard the ingest output

    exit_code = main(["extract", book_dir.name, "--provider", "fake"])

    output = capsys.readouterr().out
    assert exit_code == 0
    chapter_count = len(load_chapters(book_dir.name))
    assert f"Extracting '{book_dir.name}' - {chapter_count} chapter(s)" in output
    assert "Silence here is normal, not a hang." in output
    assert output.index("Extracting") < output.index("chapter done")


def test_extract_start_notes_name_the_model_and_omit_it_when_unknown() -> None:
    """The provider identity is worth stating up front - it is the one thing a
    resumed run can later refuse over - but `extraction_identity` returns None
    for a provider that doesn't offer one, and "via None" would be worse than
    saying nothing at all."""

    class _Identified:
        def extraction_identity(self):
            return "ollama:qwen2.5:7b-instruct"

    named = extract_start_notes("some-book", 75, 0, _Identified())
    assert "via ollama:qwen2.5:7b-instruct" in named[0]

    anonymous = extract_start_notes("some-book", 75, 0, object())
    assert "via" not in anonymous[0]
    assert "None" not in anonymous[0]

    resumed = extract_start_notes("some-book", 75, 31, _Identified())
    assert "44 remaining chapter(s)" in resumed[0]


def test_print_section_omits_an_empty_section_entirely(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The reason callers can pass a usually-empty list without guarding every
    call site. A header with nothing under it is worse than no header - and
    `extract`'s "Skipped and rejected" is empty on a healthy run, which is the
    common case, not the exception."""
    _print_section("Skipped and rejected", [])
    assert capsys.readouterr().out == ""


def test_print_section_renders_a_heading_and_indents_its_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_section("Files", ["wrote report.txt", "", "removed staged copy"])
    out = capsys.readouterr().out
    # Leading blank line separates it from whatever came before.
    assert out.startswith("\nFiles:\n")
    assert "  wrote report.txt" in out
    assert "  removed staged copy" in out
    # A blank line inside a section stays blank rather than becoming two
    # spaces of trailing whitespace.
    assert "  \n" not in out


def test_ingest_groups_its_output_under_headings(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ingest used to print four unrelated concerns as one run, separated only
    by indentation. The parse notes were the worst of it: they printed as they
    occurred, which put indented detail *above* the un-indented headline it was
    qualifying. Assert the ordering, not just that the sections exist."""
    epub_path = tmp_path / "fragmented.epub"
    build_fragmented_epub(epub_path)
    main(["ingest", str(epub_path)])

    out = capsys.readouterr().out
    for header in ("Parsing:", "Sanity check:", "Files:", "Next steps:"):
        assert header in out, f"missing section {header!r}"
    # Sections in a deliberate order: what happened, then how it was read,
    # then what was touched on disk, then what to do next.
    assert (
        out.index("Ingested ")
        < out.index("Parsing:")
        < out.index("Sanity check:")
        < out.index("Files:")
        < out.index("Next steps:")
    )
    # The consolidation note is a parse note now, not a line above the headline.
    assert out.index("consolidated 40 raw fragments into") > out.index("Parsing:")


def test_extract_separates_its_result_from_the_progress_lines(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The closing result used to run straight on from the last progress line,
    which on a 75-chapter book is exactly where it is hardest to find - and
    worse in a `--log` file read by scrolling back through hours of them."""
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    capsys.readouterr()

    main(["extract", book_dir.name, "--provider", "fake"])

    out = capsys.readouterr().out
    assert "\n\nExtracted " in out


def test_eval_with_fake_provider(tmp_path: Path, _library_root: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    exit_code = main(["eval", book_dir.name, "--chapters", "0,1", "--providers", "fake"])

    assert exit_code == 0
    # eval is read-only - it must not have created facts.jsonl/entities.json
    assert not (book_dir / "facts.jsonl").exists()
    assert not (_library_root / "entities.json").exists()


def test_chat_single_question_with_fake_provider(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_narrative_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])
    capsys.readouterr()  # discard ingest/extract output

    exit_code = main(
        ["chat", book_dir.name, "--chapter", "0", "--provider", "fake", "--question", "Who is in chapter 0?"]
    )

    assert exit_code == 0
    assert "[fake answer] Based on:" in capsys.readouterr().out


def test_chat_interactive_session_recomputes_context_per_question(
    tmp_path: Path, _library_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real behavior change: context used to be built once before the
    interactive loop even started asking for a question, so every question
    in a session saw the identical fixed blob. Retrieval is now
    question-dependent (query.select_relevant_facts), so two questions
    naming different entities must see different context."""
    epub_path = tmp_path / "sample.epub"
    build_narrative_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])

    seen_contexts: list[str] = []

    class _RecordingProvider:
        def answer_question(self, question, context, content_type="fiction"):
            seen_contexts.append(context)
            return "answer"

    monkeypatch.setattr("bookrag.cli.get_provider", lambda name=None, model=None: _RecordingProvider())

    questions = iter(["Tell me about Will", "Tell me about Halt"])

    def fake_input(_prompt: str) -> str:
        try:
            return next(questions)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main(["chat", book_dir.name, "--chapter", "1"])

    assert exit_code == 0
    assert len(seen_contexts) == 2
    assert seen_contexts[0] != seen_contexts[1]


def test_chat_passes_content_type_from_metadata_to_answer_question(
    tmp_path: Path, _library_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_narrative_epub(epub_path)
    main(["ingest", str(epub_path), "--content-type", "nonfiction"])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    seen_content_types: list[str] = []

    class _RecordingProvider:
        def answer_question(self, question, context, content_type="fiction"):
            seen_content_types.append(content_type)
            return "answer"

    monkeypatch.setattr("bookrag.cli.get_provider", lambda name=None, model=None: _RecordingProvider())

    exit_code = main(["chat", book_dir.name, "--chapter", "0", "--question", "anything"])

    assert exit_code == 0
    assert seen_content_types == ["nonfiction"]


def test_chat_rejects_out_of_range_chapter(tmp_path: Path, _library_root: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    exit_code = main(
        ["chat", book_dir.name, "--chapter", "99", "--provider", "fake", "--question", "anything"]
    )

    assert exit_code == 1


def test_chat_unknown_book_id(tmp_path: Path, _library_root: Path) -> None:
    exit_code = main(["chat", "no-such-book", "--chapter", "0", "--provider", "fake", "--question", "anything"])

    assert exit_code == 1


def test_list_command_reports_no_books_on_an_empty_library(_library_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["list"])

    assert exit_code == 0
    assert "No books in the library yet" in capsys.readouterr().out


def test_list_command_prints_a_row_per_book(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    exit_code = main(["list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "book_id" in output  # header row
    assert book_dir.name in output
    assert "Test Book" in output


def test_show_command_for_an_unextracted_book(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    exit_code = main(["show", book_dir.name])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "not yet extracted" in output


def test_show_command_unknown_book_id(_library_root: Path) -> None:
    exit_code = main(["show", "no-such-book"])

    assert exit_code == 1


def test_remove_command_with_yes_flag_deletes_the_book(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    exit_code = main(["remove", book_dir.name, "--yes"])

    assert exit_code == 0
    assert not book_dir.exists()
    assert "Removed" in capsys.readouterr().out


def test_remove_command_without_confirmation_aborts(
    tmp_path: Path, _library_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    exit_code = main(["remove", book_dir.name])

    assert exit_code == 1
    assert book_dir.exists()  # nothing removed


def test_remove_command_unknown_book_id(_library_root: Path) -> None:
    exit_code = main(["remove", "no-such-book", "--yes"])

    assert exit_code == 1


def test_doctor_command_reports_a_clean_library(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])

    exit_code = main(["doctor"])

    assert exit_code == 0
    assert "consistent" in capsys.readouterr().out


def test_doctor_command_detects_and_fixes_an_orphaned_index_entry(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    shutil.rmtree(book_dir)  # simulate a directory deleted outside the CLI

    report_exit_code = main(["doctor"])
    report_output = capsys.readouterr().out

    fix_exit_code = main(["doctor", "--fix"])
    capsys.readouterr()
    recheck_exit_code = main(["doctor"])
    recheck_output = capsys.readouterr().out

    assert report_exit_code == 0
    assert book_dir.name in report_output
    assert fix_exit_code == 0
    assert recheck_exit_code == 0
    assert "consistent" in recheck_output


def _seed_duplicate_wargal_cluster(library_root: Path, book_id: str) -> None:
    entities = load_entities(library_root)
    entities["entities"].extend(
        [
            {"entity_id": "character-a", "canonical_name": "Wargals", "type": "character", "aliases": [], "book_ids": [book_id]},
            {"entity_id": "setting-b", "canonical_name": "The Wargals", "type": "setting", "aliases": [], "book_ids": [book_id]},
        ]
    )
    save_entities(entities, library_root)
    facts_path = library_root / book_id / "facts.jsonl"
    with facts_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"entity_id": "character-a", "chapter_index": 0, "category": "development", "statement": "a"}) + "\n")
        f.write(json.dumps({"entity_id": "setting-b", "chapter_index": 0, "category": "description", "statement": "b"}) + "\n")


def test_doctor_command_reports_a_duplicate_entity_cluster(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])
    _seed_duplicate_wargal_cluster(_library_root, book_dir.name)
    capsys.readouterr()

    exit_code = main(["doctor"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "duplicate entity cluster" in output
    assert "Wargals" in output


def test_doctor_merge_duplicates_with_yes_merges_without_prompting(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])
    _seed_duplicate_wargal_cluster(_library_root, book_dir.name)
    capsys.readouterr()

    exit_code = main(["doctor", "--merge-duplicates", "--yes"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Merged" in output
    remaining_ids = {e["entity_id"] for e in load_entities(_library_root)["entities"]}
    assert len(remaining_ids & {"character-a", "setting-b"}) == 1  # exactly one of the two survives


def test_doctor_merge_duplicates_without_yes_aborts_on_no_confirmation(
    tmp_path: Path, _library_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])
    _seed_duplicate_wargal_cluster(_library_root, book_dir.name)
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    exit_code = main(["doctor", "--merge-duplicates"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Skipped" in output
    remaining_ids = {e["entity_id"] for e in load_entities(_library_root)["entities"]}
    assert {"character-a", "setting-b"} <= remaining_ids  # nothing merged


def test_aliases_command_says_so_plainly_for_a_third_person_book(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Most novels are third person. Saying "nothing to report" and why beats
    an empty list, which reads like a failure."""
    epub_path = tmp_path / "sample.epub"
    build_narrative_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    capsys.readouterr()

    exit_code = main(["aliases", book_dir.name])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "does not read as first-person" in output


def test_aliases_link_creates_an_entity_extraction_will_resolve_into(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The handoff that makes the whole pass worth running: linking before
    extraction is what stops the split forming. `test_library.py` owns the
    proof that extraction honours it; this pins the CLI plumbing and that the
    user is told what just happened."""
    epub_path = tmp_path / "sample.epub"
    build_narrative_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    capsys.readouterr()

    exit_code = main(["aliases", book_dir.name, "--link", "Conn,Connwaer"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Created 'Conn'" in output and "Connwaer" in output
    (entity,) = [e for e in load_entities(_library_root)["entities"] if e["canonical_name"] == "Conn"]
    assert entity["aliases"] == ["Connwaer"]
    assert entity["book_ids"] == [book_dir.name]


def test_aliases_rejects_an_unknown_book(capsys: pytest.CaptureFixture[str], _library_root: Path) -> None:
    assert main(["aliases", "no-such-book"]) == 1
    assert "no such book" in capsys.readouterr().out


def test_narrator_aliases_print_nothing_for_a_third_person_book() -> None:
    """Most novels are third person, and this pass has nothing to say about
    them. `_print_section` drops an empty section entirely, header included, so
    the cost to those books is zero lines - which is what lets the section be
    unconditional at the call site."""
    assert narrator_alias_lines(NarratorAliases()) == []


def test_narrator_aliases_show_their_counts_and_whether_each_reads_as_a_name() -> None:
    """The counts are how a reader separates a real alias from a stray match,
    and on a real book the gap is stark. The name/epithet mark is the other
    half: it decides what can happen to a candidate at all, since only a name
    is ever linkable or reachable from a question.

    This section still claims nothing about what was *done* - a three-party
    scene can put a bystander's title in this list, so "detected" and "acted
    on" have to stay visibly separate. The "Linked" section says what
    happened."""
    found = NarratorAliases(
        aliases=[
            AliasCandidate("boy", times_addressed=34, times_capitalised=0),
            AliasCandidate("Conn", times_addressed=13, times_capitalised=13),
            AliasCandidate("Captain", times_addressed=2, times_capitalised=2),
        ],
        first_person_chapters=[0, 1, 2],
        chapters_considered=4,
    )

    lines = narrator_alias_lines(found)

    assert "boy (34x, epithet)" in lines[0]
    assert "Conn (13x, name)" in lines[0]
    assert "3 of 4 chapters" in lines[1]
    assert not any("merged" in line.lower() or "linked as" in line.lower() for line in lines)


def _seed_name_variant_cluster(library_root: Path, book_id: str) -> None:
    """Real cluster from this project's own library: "Baron Arald" (39 facts)
    and "Arald" (10) are one man, and their names do not share a match_key -
    so the duplicate detector never saw them."""
    entities = load_entities(library_root)
    entities["entities"].extend(
        [
            {"entity_id": "character-arald-titled", "canonical_name": "Baron Arald", "type": "character", "aliases": [], "book_ids": [book_id]},
            {"entity_id": "character-arald-bare", "canonical_name": "Arald", "type": "character", "aliases": [], "book_ids": [book_id]},
        ]
    )
    save_entities(entities, library_root)
    facts_path = library_root / book_id / "facts.jsonl"
    with facts_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"entity_id": "character-arald-titled", "chapter_index": 0, "category": "description", "statement": "a"}) + "\n")
        f.write(json.dumps({"entity_id": "character-arald-titled", "chapter_index": 0, "category": "status", "statement": "b"}) + "\n")
        f.write(json.dumps({"entity_id": "character-arald-bare", "chapter_index": 0, "category": "description", "statement": "c"}) + "\n")


def test_doctor_reports_a_name_variant_cluster_with_its_evidence(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The report has to say *why*, not just list the names. The user is being
    asked to approve a permanent rewrite of fact ownership, and "these two
    names differ only by a title" is the whole basis for saying yes."""
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])
    _seed_name_variant_cluster(_library_root, book_dir.name)
    capsys.readouterr()

    exit_code = main(["doctor"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "one name under several forms" in output
    assert "Baron Arald" in output
    assert "title or rank" in output
    assert "--merge-name-variants" in output


def test_doctor_merge_name_variants_with_yes_records_the_other_name_as_an_alias(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The user-visible payoff: after merging, the surviving entity carries
    the other spelling as an alias, which is the field `select_relevant_facts`
    has always searched and that nothing until now populated from a book."""
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])
    _seed_name_variant_cluster(_library_root, book_dir.name)
    capsys.readouterr()

    exit_code = main(["doctor", "--merge-name-variants", "--yes"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Merged" in output
    by_id = {e["entity_id"]: e for e in load_entities(_library_root)["entities"]}
    assert "character-arald-bare" not in by_id  # the 1-fact entity loses
    assert by_id["character-arald-titled"]["aliases"] == ["Arald"]


def test_doctor_merge_name_variants_declined_leaves_both_entities_alone(
    tmp_path: Path, _library_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])
    _seed_name_variant_cluster(_library_root, book_dir.name)
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    exit_code = main(["doctor", "--merge-name-variants"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Skipped" in output
    remaining = {e["entity_id"] for e in load_entities(_library_root)["entities"]}
    assert {"character-arald-titled", "character-arald-bare"} <= remaining


def test_doctor_fix_never_merges_a_name_variant(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same posture as duplicate clusters and cross-book splits. `--fix` is
    for cleanups of clearly-dead data; merging picks a winner and permanently
    rewrites which entity owns a fact."""
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["extract", book_dir.name, "--provider", "fake"])
    _seed_name_variant_cluster(_library_root, book_dir.name)
    capsys.readouterr()

    main(["doctor", "--fix"])

    remaining = {e["entity_id"] for e in load_entities(_library_root)["entities"]}
    assert {"character-arald-titled", "character-arald-bare"} <= remaining


def test_extract_refuses_a_model_mismatch_before_announcing_a_resume(
    tmp_path: Path, _library_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal has to land *before* "Resuming from chapter N", or the
    user is told a multi-hour run has started and then that it hasn't. It
    also must not call the provider at all - the point is that no second
    model's facts reach the file."""
    epub_path = tmp_path / "sample.epub"
    build_narrative_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    progress_path = book_dir / "extraction_progress.json"
    chapter_count = len(load_chapters(book_dir.name))
    progress_path.write_text(
        json.dumps(
            {
                "chapter_count": chapter_count,
                "next_chapter_index": 1,
                "provider": "ollama:qwen2.5:7b-instruct",
            }
        ),
        encoding="utf-8",
    )

    class _NeverCalledProvider:
        calls = 0

        def extraction_identity(self):
            return "ollama:llama3.2:3b"

        def extract_facts(self, *a, **kw):
            type(self).calls += 1
            return []

    monkeypatch.setattr("bookrag.cli.get_provider", lambda name=None, model=None: _NeverCalledProvider())

    exit_code = main(["extract", book_dir.name])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Refusing to resume" in out
    # The announcement line specifically, not the word "Resuming" - the
    # refusal's own text legitimately contains "Resuming would append...".
    assert f"Resuming '{book_dir.name}'" not in out
    assert "ollama:qwen2.5:7b-instruct" in out and "ollama:llama3.2:3b" in out
    assert "--restart" in out
    # The start-of-run banner must be held back by the same refusal, for the
    # same reason as the "Resuming" line - a refused run never starts, so
    # announcing what it is about to extract is exactly as wrong.
    assert "Extracting" not in out
    assert _NeverCalledProvider.calls == 0
    # Progress left exactly as it was - a refusal must not be destructive.
    assert json.loads(progress_path.read_text(encoding="utf-8"))["provider"] == "ollama:qwen2.5:7b-instruct"


def test_ingest_tells_the_user_how_to_extract(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ingest does not extract anything, and nothing used to say what came
    next - the reported gap this guidance exists to close."""
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    main(["ingest", str(epub_path)])

    out = capsys.readouterr().out
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    assert f"bookrag extract {book_dir.name}" in out
    assert "--provider fake" in out


def test_ingest_tells_the_user_how_to_follow_a_long_run(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A multi-hour run has to be backgrounded, which is exactly when its
    progress lines stop being visible."""
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)

    main(["ingest", str(epub_path)])

    out = capsys.readouterr().out
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    assert "--log" in out
    assert str(default_log_path(book_dir.name)) in out
    assert "tail -f" in out or "Get-Content -Wait" in out


def test_extract_log_writes_progress_to_a_file(tmp_path: Path, _library_root: Path) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    log_path = tmp_path / "run.log"

    exit_code = main(["extract", book_dir.name, "--provider", "fake", "--log", str(log_path)])

    assert exit_code == 0
    logged = log_path.read_text(encoding="utf-8")
    assert "chapter done" in logged
    assert "Extracted" in logged


def test_extract_log_still_prints_to_the_console(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--log tees, it does not redirect - a foreground run must still show
    progress in the terminal."""
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    capsys.readouterr()

    main(["extract", book_dir.name, "--provider", "fake", "--log", str(tmp_path / "run.log")])

    out = capsys.readouterr().out
    assert "chapter done" in out


def test_extract_log_with_no_path_uses_the_documented_default(
    tmp_path: Path, _library_root: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The path ingest prints must be the path --log actually writes to, or
    the follow command is wrong."""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]

    main(["extract", book_dir.name, "--provider", "fake", "--log"])

    expected = tmp_path / f"extract_{book_dir.name}.log"
    assert expected.exists()
    assert "chapter done" in expected.read_text(encoding="utf-8")
    assert str(expected) in capsys.readouterr().out


def test_extract_log_appends_so_a_resumed_run_keeps_the_earlier_output(
    tmp_path: Path, _library_root: Path
) -> None:
    """An interrupted run is resumed with the same command; the first
    attempt's output is exactly what you want when working out why it died."""
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    log_path = tmp_path / "run.log"

    main(["extract", book_dir.name, "--provider", "fake", "--log", str(log_path)])
    main(["extract", book_dir.name, "--provider", "fake", "--restart", "--log", str(log_path)])

    assert log_path.read_text(encoding="utf-8").count("=== bookrag extract") == 2


def test_extract_log_reports_an_unusable_path_instead_of_crashing(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    epub_path = tmp_path / "sample.epub"
    build_sample_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    blocked = tmp_path / "a-file"
    blocked.write_text("not a directory", encoding="utf-8")

    exit_code = main(["extract", book_dir.name, "--provider", "fake", "--log", str(blocked / "run.log")])

    assert exit_code == 1
    assert "Could not open log file" in capsys.readouterr().out


def test_tee_flushes_every_write_so_a_follower_sees_progress_live(tmp_path: Path) -> None:
    """The reason --log exists at all. Python block-buffers a file, so an
    unflushed log shows a follower nothing for minutes on end during a run
    whose entire purpose is watching it progress."""
    log_path = tmp_path / "run.log"
    sink = io.StringIO()

    with log_path.open("a", encoding="utf-8") as handle:
        tee = _Tee(sink, handle)
        tee.write("  [1/75] chapter done\n")
        # Deliberately read before the handle is closed - that is what a
        # `tail -f` running in another terminal is doing.
        assert log_path.read_text(encoding="utf-8") == "  [1/75] chapter done\n"

    assert sink.getvalue() == "  [1/75] chapter done\n"


def _characters(library_root: Path) -> list[dict]:
    return [e for e in load_entities(library_root)["entities"] if e["type"] == "character"]


def test_ingest_links_a_first_person_narrators_names_without_being_asked(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """**The point of the whole feature.** A reader's flow is download, drop in
    `data/incoming/`, ingest, extract - nothing in it goes near a linking
    command. So a link that waits to be invoked is invisible, which is exactly
    the fault of `doctor --merge-name-variants`, and a tester's re-ingest
    reproduces the same fragmented library it was meant to fix.

    Runs with no terminal attached (pytest captures stdout), because the
    approach this replaced was an interactive prompt - it needed a person
    present who could judge a book's cast, per book."""
    epub_path = tmp_path / "first_person.epub"
    build_first_person_epub(epub_path)

    exit_code = main(["ingest", str(epub_path)])

    assert exit_code == 0
    (entity,) = _characters(_library_root)
    assert entity["canonical_name"] == "Conn"
    assert entity["aliases"] == ["Connwaer"]
    assert entity["epithets"] == ["boy"]

    output = capsys.readouterr().out
    assert "'Conn' also answers to Connwaer" in output
    # An automatic, heuristic-driven merge has to say how to undo itself.
    assert "--unlink" in output


def test_ingest_no_auto_link_leaves_the_names_separate(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The baseline escape hatch: still detects and reports, links nothing."""
    epub_path = tmp_path / "first_person.epub"
    build_first_person_epub(epub_path)

    exit_code = main(["ingest", str(epub_path), "--no-auto-link"])

    assert exit_code == 0
    assert _characters(_library_root) == []
    output = capsys.readouterr().out
    assert "skipped (--no-auto-link)" in output
    assert "Connwaer" in output  # detection still ran and still reported


def test_aliases_unlink_separates_the_names_again(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """What makes automatic linking acceptable at all. A heuristic will
    sometimes be wrong, and "wrong and permanent" is a different proposition
    from "wrong and one command away"."""
    epub_path = tmp_path / "first_person.epub"
    build_first_person_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    capsys.readouterr()

    exit_code = main(["aliases", book_dir.name, "--unlink"])

    assert exit_code == 0
    (entity,) = _characters(_library_root)
    assert entity["aliases"] == []
    assert entity["epithets"] == []
    assert json.loads((book_dir / "declared_aliases.json").read_text(encoding="utf-8"))["groups"] == []
    assert "Unlinked" in capsys.readouterr().out


def test_a_third_person_book_is_left_alone(tmp_path: Path, _library_root: Path) -> None:
    """Most books are third person, and there is no attribution signal there -
    a vocative is findable but nothing says who it was aimed at. Ingest must be
    silent rather than guess, or auto-linking becomes a liability on the
    common case rather than a win on the rare one."""
    epub_path = tmp_path / "narrative.epub"
    build_narrative_epub(epub_path)

    assert main(["ingest", str(epub_path)]) == 0
    assert _characters(_library_root) == []


def test_extract_after_unlinking_warns_instead_of_crashing(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The recovery path, which shipped broken. `--unlink` tells the user to
    re-run `bookrag extract --restart`, and that command died with a
    `TypeError` - so the one instruction printed to somebody undoing a wrong
    link was the one instruction that did not work.

    Ingest-only tests cannot reach this: nothing is declared *yet* at ingest
    time either way, so the warning is silent there. It needs an extract that
    runs *after* the link was removed."""
    epub_path = tmp_path / "first_person.epub"
    build_first_person_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    main(["aliases", book_dir.name, "--unlink"])
    capsys.readouterr()

    exit_code = main(["extract", book_dir.name, "--provider", "fake", "--restart"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "nothing links them yet" in output
    assert "Conn" in output


def test_extract_after_no_auto_link_warns_instead_of_crashing(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other way to reach the same line: opting out at ingest rather than
    undoing afterwards. Same crash, same silence from ingest-only tests."""
    epub_path = tmp_path / "first_person.epub"
    build_first_person_epub(epub_path)
    main(["ingest", str(epub_path), "--no-auto-link"])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    capsys.readouterr()

    exit_code = main(["extract", book_dir.name, "--provider", "fake"])

    assert exit_code == 0
    assert "nothing links them yet" in capsys.readouterr().out


def test_extract_says_nothing_about_aliases_when_the_link_is_in_place(
    tmp_path: Path, _library_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The normal path stays quiet. Auto-linking already handled it at ingest,
    and repeating the warning here would train the reader to ignore it."""
    epub_path = tmp_path / "first_person.epub"
    build_first_person_epub(epub_path)
    main(["ingest", str(epub_path)])
    (book_dir,) = [p for p in _library_root.iterdir() if p.is_dir()]
    capsys.readouterr()

    main(["extract", book_dir.name, "--provider", "fake"])

    assert "nothing links them yet" not in capsys.readouterr().out
