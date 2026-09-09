# Context Index

One line per source file: path, then a one-line purpose. Keep in sync whenever a
context doc under `context/` is added, removed, or its purpose changes materially.

- [src/bookrag/__init__.py](src/bookrag/__init__.py.md) — package marker, declares `__version__`.
- [src/bookrag/ingest/__init__.py](src/bookrag/ingest/__init__.py.md) — `ingest` subpackage marker.
- [src/bookrag/ingest/chapter.py](src/bookrag/ingest/chapter.py.md) — shared `Chapter` data model used by every loader.
- [src/bookrag/ingest/epub_loader.py](src/bookrag/ingest/epub_loader.py.md) — loads an `.epub` into per-chapter plain text, in reading order.
- [src/bookrag/ingest/pdf_loader.py](src/bookrag/ingest/pdf_loader.py.md) — loads a `.pdf` into per-chapter plain text via its TOC/outline.
- [src/bookrag/ingest/consolidate.py](src/bookrag/ingest/consolidate.py.md) — merges many small/incoherent chapter fragments into larger, coherent ones for extraction.
- [src/bookrag/storage.py](src/bookrag/storage.py.md) — persists a book (source + chapters + metadata incl. `content_type`) to `data/library/<book_id>/`; series-aware index + reading-order helper.
- [src/bookrag/query.py](src/bookrag/query.py.md) — `facts_as_of`: the spoiler-safety filter primitive; `format_context` renders facts for a provider.
- [src/bookrag/eval.py](src/bookrag/eval.py.md) — read-only provider comparison: side-by-side report + groundedness score.
- [src/bookrag/cli.py](src/bookrag/cli.py.md) — `bookrag ingest|extract|eval|chat|list|show|remove|doctor` CLI entry point.
- [src/bookrag/library.py](src/bookrag/library.py.md) — library-wide list/show/remove/doctor: extraction-status summaries and index/entities.json consistency cleanup.
- [src/bookrag/titles.py](src/bookrag/titles.py.md) — last-resort title/author guess from a filename.
- [src/bookrag/providers/__init__.py](src/bookrag/providers/__init__.py.md) — `providers` subpackage marker.
- [src/bookrag/providers/base.py](src/bookrag/providers/base.py.md) — `ExtractedFact`, `Provider` Protocol (`extract_facts` + `answer_question`), `ExtractionParseError`.
- [src/bookrag/providers/fake_provider.py](src/bookrag/providers/fake_provider.py.md) — deterministic no-network provider, for tests.
- [src/bookrag/providers/anthropic_provider.py](src/bookrag/providers/anthropic_provider.py.md) — Claude-backed provider (untested - no API credential available).
- [src/bookrag/providers/ollama_provider.py](src/bookrag/providers/ollama_provider.py.md) — local, no-API-key provider via Ollama; the practical default.
- [src/bookrag/providers/prompts.py](src/bookrag/providers/prompts.py.md) — shared extraction and answer-question system prompts.
- [src/bookrag/providers/parsing.py](src/bookrag/providers/parsing.py.md) — shared lenient JSON-to-`ExtractedFact` parsing; owns the fiction/nonfiction entity-type/category taxonomies and the Ollama structured-output schema.
- [src/bookrag/providers/registry.py](src/bookrag/providers/registry.py.md) — `get_provider(name)` lookup; `DEFAULT_PROVIDER = "ollama"`.
- [src/bookrag/extract/__init__.py](src/bookrag/extract/__init__.py.md) — `extract` subpackage marker.
- [src/bookrag/extract/resolve.py](src/bookrag/extract/resolve.py.md) — entity name → `entity_id` resolution against `data/library/entities.json`.
- [src/bookrag/extract/pipeline.py](src/bookrag/extract/pipeline.py.md) — `extract_book`: runs a provider over every chapter, writes `facts.jsonl`.
- [tests/helpers.py](../tests/helpers.py.md) — shared synthetic epub/pdf builders.
- [tests/test_epub_loader.py](../tests/test_epub_loader.py.md) — covers `epub_loader` (chapters + metadata) with a synthetic in-test epub.
- [tests/test_consolidate.py](../tests/test_consolidate.py.md) — covers `ingest.consolidate`'s trigger decision and merge logic.
- [tests/test_pdf_loader.py](../tests/test_pdf_loader.py.md) — covers `pdf_loader` (chapters + metadata), TOC and no-TOC fallback paths.
- [tests/test_storage.py](../tests/test_storage.py.md) — covers `storage.py`, including the series/chapter-2-collision guarantee.
- [tests/test_storage_series_reading_order.py](../tests/test_storage_series_reading_order.py.md) — covers `series_reading_order`.
- [tests/test_cli.py](../tests/test_cli.py.md) — end-to-end `bookrag ingest|extract|eval` coverage, plus CLI-plumbing coverage of `list|show|remove|doctor`.
- [tests/test_library.py](../tests/test_library.py.md) — covers `library.py`'s list/show/remove/doctor logic in depth.
- [tests/test_titles.py](../tests/test_titles.py.md) — covers `titles.guess_title_author`, including the real `Finite-and-Infinite-Games-by-James-Carse` case.
- [tests/test_resolve.py](../tests/test_resolve.py.md) — covers entity resolution (exact/alias match, type separation).
- [tests/test_fake_provider.py](../tests/test_fake_provider.py.md) — covers `FakeProvider`'s deterministic extraction.
- [tests/test_extraction_pipeline.py](../tests/test_extraction_pipeline.py.md) — covers `extract_book`, including series entity-seeding.
- [tests/test_query.py](../tests/test_query.py.md) — covers `facts_as_of`'s spoiler-safety guarantee across a series.
- [tests/test_eval.py](../tests/test_eval.py.md) — covers `groundedness_score`, `run_eval`'s read-only guarantee, and `summarize`.
- [tests/test_ingestion_report.py](../tests/test_ingestion_report.py.md) — covers `classify_ingestion`/`write_ingestion_report`.
- [tests/test_parsing.py](../tests/test_parsing.py.md) — covers `providers.parsing.parse_facts`.
- [tests/test_ollama_provider.py](../tests/test_ollama_provider.py.md) — real integration smoke test against a running Ollama, skipped when unreachable.
- [tests/test_registry.py](../tests/test_registry.py.md) — covers `get_provider`'s model-override/env-var resolution and unknown-provider error.
