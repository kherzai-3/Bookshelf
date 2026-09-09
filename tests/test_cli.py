import json
import shutil
from pathlib import Path

import pytest

from bookrag.cli import main
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
