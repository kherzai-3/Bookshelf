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
    _Tee,
    _use_utf8_output,
    default_log_path,
    extract_start_notes,
    main,
)
from bookrag.extract.resolve import load_entities, save_entities
from bookrag.storage import load_chapters
from tests.helpers import build_fragmented_epub, build_narrative_epub, build_sample_epub


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
